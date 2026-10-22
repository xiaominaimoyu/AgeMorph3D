"""Generate offline BLEND display experiments from fixed registered UV anchors.

Linear-light interpolation of existing pixels is not fractional SAM generation,
age/identity quality, or a production endpoint. Filename ages remain research
labels; API source_age stays unknown, including exact original-asset copies.
"""

# ruff: noqa: E402 -- Standalone entrypoint uses existing numerical helpers.

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import re
import struct
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))
sys.path.insert(0, str(_ROOT / "tools"))

import numpy as np
from age_protocol import _load, _path, _pin
from agemorph3d.age_continuity import (
    display_step_metrics,
    quantize_display_rgba,
    sample_display_rgba,
    support_metrics,
    validate_age,
)
from agemorph3d.static_mesh import _encode_glb
from PIL import Image

PROTOCOL_ID = "agemorph3d-blend-display-v1"
UNKNOWN_AGE = {"value": None, "method": "unknown", "calibration_id": None}
_GEOMETRY = (
    "source_positions_sha256",
    "source_normals_sha256",
    "source_indices_sha256",
    "gltf_uv_sha256",
)
_CODE = (
    "tools/blend_display_probe.py",
    "tools/age_protocol.py",
    "backend/src/agemorph3d/age_continuity.py",
    "backend/src/agemorph3d/static_mesh.py",
    "backend/src/agemorph3d/schemas.py",
)
_PROTOCOLS = ("docs/blend-display-v1.json", "docs/blend-display-controls-v1.json")


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _container(data: bytes) -> tuple:
    if len(data) < 28 or len(data) > 64 * 1024**2:
        raise ValueError("GLB must be a bounded complete container.")
    magic, version, total, length, kind = struct.unpack_from("<4sIII4s", data)
    if (
        magic != b"glTF"
        or version != 2
        or total != len(data)
        or kind != b"JSON"
        or 28 + length > len(data)
    ):
        raise ValueError("Invalid GLB header.")
    binary_length, binary_kind = struct.unpack_from("<I4s", data, 20 + length)
    binary = data[28 + length :]
    if binary_kind != b"BIN\0" or binary_length != len(binary):
        raise ValueError("Invalid GLB binary chunk.")
    return json.loads(data[20 : 20 + length]), binary


def _decode(data: bytes) -> tuple:
    document, binary = _container(data)
    primitive = document["meshes"][0]["primitives"][0]
    if (
        document["extras"]["source_age"] != UNKNOWN_AGE
        or document["extras"]["asset_mode"] != "static"
        or any("uri" in row for row in document["images"] + document["buffers"])
        or "targets" in primitive
        or document.get("animations")
    ):
        raise ValueError("Display inputs must be self-contained, static and API unknown-age.")
    arrays = []
    for identifier, components, dtype, component_type, accessor_type in (
        (primitive["attributes"]["POSITION"], 3, "<f4", 5126, "VEC3"),
        (primitive["attributes"]["NORMAL"], 3, "<f4", 5126, "VEC3"),
        (primitive["indices"], 1, "<u4", 5125, "SCALAR"),
        (primitive["attributes"]["TEXCOORD_0"], 2, "<f4", 5126, "VEC2"),
    ):
        accessor = document["accessors"][identifier]
        view = document["bufferViews"][accessor["bufferView"]]
        if (
            accessor["componentType"] != component_type
            or accessor["type"] != accessor_type
            or accessor.get("sparse")
            or view.get("byteStride")
        ):
            raise ValueError("Unexpected static GLB accessor layout.")
        array = np.frombuffer(
            binary,
            dtype=dtype,
            count=accessor["count"] * components,
            offset=view.get("byteOffset", 0) + accessor.get("byteOffset", 0),
        ).copy()
        if not np.isfinite(array).all():
            raise ValueError("GLB geometry and UV must be finite.")
        arrays.append(array.reshape(-1, 3 if components == 1 else components))
    view = document["bufferViews"][document["images"][0]["bufferView"]]
    png = binary[view["byteOffset"] : view["byteOffset"] + view["byteLength"]]
    return (
        document,
        arrays,
        png,
        {key: _hash(array.tobytes()) for key, array in zip(_GEOMETRY, arrays, strict=True)},
    )


def _rgba(png: bytes, size: int) -> np.ndarray:
    with Image.open(io.BytesIO(png)) as image:
        if image.format != "PNG" or image.mode != "RGBA" or image.size != (size, size):
            raise ValueError("Anchors must be common-size RGBA PNGs.")
        rgba = np.asarray(image).copy()
    support_metrics(rgba, rgba)
    return rgba


def _pin_path(root: Path, plan: dict, pin: dict) -> Path:
    path = _path(root, pin["path"])
    if plan["inputs"].get(path.relative_to(root).as_posix()) != {
        "sha256": pin["sha256"],
        "bytes": pin["bytes"],
    }:
        raise ValueError("Every used report/atlas/GLB must be explicitly frozen in plan.inputs.")
    _pin(root, path, pin["sha256"], pin["bytes"])
    return path


def _verify_plan(root: Path, plan: dict) -> None:
    if (
        plan.get("protocol_id") != PROTOCOL_ID
        or plan.get("epsilon_years") != 0.001
        or type(plan.get("atlas_size")) is not int
        or not 4 <= plan["atlas_size"] <= 1024
        or any(
            type(plan.get(key)) is not int or plan[key] < 1
            for key in ("expected_sources", "expected_generated", "expected_intervals")
        )
        or not isinstance(plan.get("inputs"), dict)
        or not set(_CODE + _PROTOCOLS) <= set(plan["inputs"])
    ):
        raise ValueError("Unsupported or incomplete pre-measurement display plan.")
    for name, pin in plan["inputs"].items():
        if set(pin) != {"sha256", "bytes"}:
            raise ValueError("Plan entries must declare complete SHA-256 and byte size.")
        _pin(root, _path(root, name), pin["sha256"], pin["bytes"])


def load_inputs(args) -> tuple:
    root, plan = args.root, _load(args.study_plan)
    _verify_plan(root, plan)
    registration = _load(_pin_path(root, plan, plan["registration_report"]))
    reset = _load(_pin_path(root, plan, plan["source_reset_report"]))
    if (
        registration["protocol_id"] != "agemorph3d-target-uv-v1"
        or reset["protocol_id"] != "agemorph3d-source-reset-v1"
    ):
        raise ValueError("Display inputs must use registered N4 and original-source evidence.")
    for report in (registration, reset):
        if (
            report["research_only"] is not True
            or report["service_ready"] is not False
            or report["g3_complete"] is not False
        ):
            raise ValueError("Input research acceptance boundaries must remain closed.")
    originals = {row["sample_id"]: row for row in reset["records"]}
    targets = registration["records"]
    if (
        len(originals) != len(reset["records"])
        or len(originals) != plan["expected_sources"]
        or len(targets) != plan["expected_generated"]
        or len({row["sample_id"] for row in targets}) != len(targets)
    ):
        raise ValueError("Display inputs differ from the complete frozen source/target cohort.")
    groups = {}
    for row in targets:
        source_id = row["source_id"]
        if (
            source_id not in originals
            or not re.fullmatch(r"[a-zA-Z0-9_-]+", source_id)
            or row["status"] != "ok"
            or row["source_age"] != UNKNOWN_AGE
            or row["capabilities"] != {"age_morph": False, "age_texture": False}
        ):
            raise ValueError("Generated cohort must preserve successful static development inputs.")
        invariants = registration["source_geometry_invariants"][source_id]
        glb = _pin_path(root, plan, row["artifacts"]["glb"]).read_bytes()
        png = _pin_path(root, plan, row["artifacts"]["atlas"]).read_bytes()
        document, arrays, embedded, hashes = _decode(glb)
        if (
            embedded != png
            or hashes != invariants
            or any(row[key] != hashes[key] for key in _GEOMETRY)
        ):
            raise ValueError("Registered anchors differ from immutable source geometry/common UV.")
        group = groups.setdefault(source_id, {"anchors": {}, "rows": {}, "geometry": hashes})
        age = validate_age(row["target_age"])
        if age in group["anchors"]:
            raise ValueError("A source cannot have duplicate SAM condition anchors.")
        group["anchors"][age] = _rgba(png, plan["atlas_size"])
        group["rows"][age] = row
    if set(groups) != set(originals):
        raise ValueError("Every original source must have registered condition anchors.")
    for source_id, group in groups.items():
        if min(group["anchors"]) != 20 or max(group["anchors"]) != 70:
            raise ValueError("Display inputs must retain the 20/70 boundary condition anchors.")
        original = originals[source_id]
        if (
            original["status"] != "ok"
            or original["source_age"] != UNKNOWN_AGE
            or original["group"] != "development"
        ):
            raise ValueError(
                "Original source must remain successful, development-only and unknown-age."
            )
        glb = _pin_path(root, plan, original["artifacts"]["glb"]).read_bytes()
        png = _pin_path(root, plan, original["artifacts"]["atlas"]).read_bytes()
        document, arrays, embedded, hashes = _decode(glb)
        if embedded != png or hashes != group["geometry"]:
            raise ValueError("Original source geometry/common UV differs from its N4 anchors.")
        label = validate_age(original["label_source_age"], allow_unknown=True)
        if any(row["source_age_label"] != label for row in group["rows"].values()):
            raise ValueError("Research labels changed between original and registered evidence.")
        if (label is None and original["reset_status"] != "source_age_unknown") or (
            label is not None and original["reset_status"] != "passed"
        ):
            raise ValueError(
                "Original-source reset evidence is inconsistent with its research label."
            )
        group.update(
            original=original,
            original_glb=glb,
            original_png=png,
            document=document,
            arrays=arrays,
            label=label,
            sam_ages=sorted(group["anchors"]),
        )
        if label is not None:
            group["anchors"][label] = _rgba(png, plan["atlas_size"])
    intervals = sum(len(group["sam_ages"]) - 1 for group in groups.values())
    if intervals != plan["expected_intervals"]:
        raise ValueError("Original N4 interval count differs from the frozen display plan.")
    return plan, groups


def _id(source_id: str, age: float) -> str:
    return source_id + "--display-" + format(age, ".6f").replace(".", "p")


def _material(data: bytes, mode: str) -> bytes:
    document, binary = _container(data)
    material = document["materials"][0]
    material.update(name="Experimental_Linear_Light_Display", alphaMode=mode)
    if mode == "BLEND":
        material.pop("alphaCutoff", None)
    encoded = json.dumps(document, allow_nan=False, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    return (
        struct.pack("<4sIII4s", b"glTF", 2, 28 + len(encoded) + len(binary), len(encoded), b"JSON")
        + encoded
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )


def _case(root, output, source_id, group, age) -> dict:
    exact = age == group["label"]
    display = sample_display_rgba(group["anchors"], age)
    rgba = quantize_display_rgba(display)
    if exact:
        png, glb, mode, kind = group["original_png"], group["original_glb"], "MASK", "source_exact"
        mask_glb = None
        blend_control = _material(glb, "BLEND")
    else:
        buffer = io.BytesIO()
        Image.fromarray(rgba).save(buffer, "PNG")
        png = buffer.getvalue()
        kind = "sam_anchor" if age in group["sam_ages"] else "blend_display"
        mode = "BLEND"
        extras = copy.deepcopy(group["document"]["extras"])
        extras["base_texture"] = {
            "kind": "experimental_linear_light_age_display",
            "age_generated": False,
            "not_original_photo_observation": True,
        }
        extras["experimental_age_display"] = {
            "source_id": source_id,
            "condition_age": age,
            "source_research_label": group["label"],
            "anchor_ages": sorted(group["anchors"]),
            "service_ready": False,
            "quality_accepted": False,
        }
        vertices, normals, triangles, uv = group["arrays"]
        encoded = _encode_glb(
            vertices, normals, triangles, extras, SimpleNamespace(png=png, gltf_uv=uv)
        )
        glb, mask_glb = _material(encoded, "BLEND"), _material(encoded, "MASK")
        blend_control = None
    _, _, embedded, hashes = _decode(glb)
    if embedded != png or hashes != group["geometry"]:
        raise ValueError("Display output changed its PNG bytes or source geometry/common UV.")
    directory = output / _id(source_id, age)
    directory.mkdir()
    artifacts = {}
    payloads = [("atlas", "atlas.png", png), ("glb", "mesh.glb", glb)]
    if mask_glb is not None:
        payloads.append(("mask_glb", "mask-baseline.glb", mask_glb))
    if blend_control is not None:
        payloads.append(("blend_control_glb", "source-material-blend-control.glb", blend_control))
    for key, name, data in payloads:
        path = directory / name
        with path.open("xb") as stream:
            stream.write(data)
        artifacts[key] = _pin(root, path)
    ages = sorted(group["anchors"])
    active = (
        [age] if age in ages else [max(a for a in ages if a < age), min(a for a in ages if a > age)]
    )
    anchor_inputs = [
        {
            "age": anchor,
            "kind": "original_source" if anchor == group["label"] else "sam_condition",
            "artifacts": {
                key: (
                    group["original"]["artifacts"]
                    if anchor == group["label"]
                    else group["rows"][anchor]["artifacts"]
                )[key]
                for key in ("atlas", "glb")
            },
        }
        for anchor in active
    ]
    return {
        "sample_id": directory.name,
        "source_id": source_id,
        "target_age": age,
        "kind": kind,
        "source_research_label": group["label"],
        "source_age": dict(UNKNOWN_AGE),
        "status": "ok",
        "source_reset_status": "SOURCE_AGE_UNKNOWN"
        if group["label"] is None
        else "offline_original_anchor",
        "artifacts": artifacts,
        "inputs": {"active_anchors": anchor_inputs},
        "expected_geometry": hashes,
        "material_alpha_mode": mode,
        "source_material_control_kind": "source_material_control" if exact else None,
        "rgba_sha256": _hash(rgba.tobytes()),
        "alpha_sha256": _hash(rgba[:, :, 3].tobytes()),
        "nonzero_alpha_texels": int(np.count_nonzero(rgba[:, :, 3])),
        "fractional_alpha_texels": int(
            np.count_nonzero((rgba[:, :, 3] > 0) & (rgba[:, :, 3] < 255))
        ),
        "unknown_rgba_zero": bool(np.all(rgba[rgba[:, :, 3] == 0] == 0)),
        "quantization_max_composite_channel_error": display_step_metrics(display, display)[
            "quantization_max_composite_channel_error"
        ],
        "original_source_bytes_exact": bool(
            exact and png == group["original_png"] and glb == group["original_glb"]
        ),
    }


def _schedule(groups: dict, epsilon: float) -> tuple:
    requests, pairs = set(), []
    for source_id, group in groups.items():
        ages, anchors, label = group["sam_ages"], group["anchors"], group["label"]
        requests.update((source_id, age) for age in (20.0, 70.0))
        if label is not None:
            requests.add((source_id, label))
        for lo, hi in zip(ages, ages[1:], strict=False):
            midpoint, step = (lo + hi) / 2, min(epsilon, (hi - lo) / 4)
            before, after = midpoint - step, midpoint + step
            requests.update(((source_id, before), (source_id, after)))
            pairs.append(
                {
                    "source_id": source_id,
                    "kind": "interval_midpoint",
                    "left_age": lo,
                    "right_age": hi,
                    "before_age": before,
                    "after_age": after,
                    "support_xor_texels": support_metrics(anchors[lo], anchors[hi])[
                        "support_xor_texels"
                    ],
                }
            )
        if label is not None:
            lower, upper = min(anchors), max(anchors)
            before, after = max(lower, label - epsilon), min(upper, label + epsilon)
            if before < after:
                requests.update(((source_id, before), (source_id, after)))
                left = max((age for age in anchors if age < label), default=label)
                right = min((age for age in anchors if age > label), default=label)
                a = support_metrics(anchors[left], anchors[label])["support_xor_texels"]
                b = support_metrics(anchors[label], anchors[right])["support_xor_texels"]
                pairs.append(
                    {
                        "source_id": source_id,
                        "kind": "source_neighborhood",
                        "source_exact_id": _id(source_id, label),
                        "before_age": before,
                        "after_age": after,
                        "support_xor_texels": max(a, b),
                        "source_left_support_xor": a,
                        "source_right_support_xor": b,
                    }
                )
    for pair in pairs:
        source_id, anchors = pair["source_id"], groups[pair["source_id"]]["anchors"]
        pair.update(
            before_id=_id(source_id, pair["before_age"]), after_id=_id(source_id, pair["after_age"])
        )
        pair["numeric_display_step"] = display_step_metrics(
            sample_display_rgba(anchors, pair["before_age"]),
            sample_display_rgba(anchors, pair["after_age"]),
        )
    return sorted(requests), pairs


def run(args) -> dict:
    research = (args.root / "output" / "research").resolve()
    output = args.output_dir.resolve()
    if research not in output.parents:
        raise ValueError("Output must be a new subdirectory under workspace output/research.")
    if args.output_dir.exists():
        raise ValueError("Output directory must not already exist.")
    plan, groups = load_inputs(args)
    requests, pairs = _schedule(groups, plan["epsilon_years"])
    args.output_dir.mkdir(parents=True, exist_ok=False)
    records = []
    for source_id, age in requests:
        records.append(_case(args.root, args.output_dir, source_id, groups[source_id], age))
    _verify_plan(args.root, plan)
    report = {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "research_only": True,
        "service_ready": False,
        "g3_complete": False,
        "production_continuity_accepted": False,
        "age_texture_quality_accepted": False,
        "identity_quality_accepted": False,
        "years_calibrated": False,
        "source_age_api_policy": "unknown",
        "new_model_inference": False,
        "holdout_age_results_opened": False,
        "inputs": {
            "study_plan": _pin(args.root, args.study_plan),
            "registration_report": plan["registration_report"],
            "source_reset_report": plan["source_reset_report"],
        },
        "records": records,
        "pair_probes": pairs,
        "source_anchors": [
            {
                "source_id": key,
                "research_label": value["label"],
                "sam_condition_ages": value["sam_ages"],
                "display_anchor_ages": sorted(value["anchors"]),
                "source_anchor_status": "SOURCE_AGE_UNKNOWN"
                if value["label"] is None
                else "original_replaces_same_age_sam",
                "original_artifacts": value["original"]["artifacts"],
            }
            for key, value in groups.items()
        ],
        "summary": {
            "sources": len(groups),
            "generated_anchor_inputs": plan["expected_generated"],
            "records": len(records),
            "pair_probes": len(pairs),
            "original_interval_pairs": plan["expected_intervals"],
            "exact_original_source_cases": sum(row["kind"] == "source_exact" for row in records),
            "unknown_source_anchors": sum(value["label"] is None for value in groups.values()),
            "all_geometry_and_uv_hashes_exact": True,
            "all_unknown_rgba_zero": all(row["unknown_rgba_zero"] for row in records),
        },
        "limitations": [
            "Atlas interpolation is not fractional SAM inference or verified age/identity.",
            "BLEND still needs quantization, depth sorting and real rendered checks.",
            "Exact originals retain MASK GLB bytes; this is offline display, not API reset.",
            "Original-photo support, occlusion, seams and production acceptance remain unapproved.",
        ],
    }
    with (args.output_dir / "report.json").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument("--study-plan", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    try:
        args.study_plan = _path(args.root, args.study_plan)
        args.output_dir = _path(args.root, args.output_dir)
        run(args)
    except (OSError, ValueError, KeyError, TypeError, struct.error) as error:
        print(f"BLEND display probe rejected: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

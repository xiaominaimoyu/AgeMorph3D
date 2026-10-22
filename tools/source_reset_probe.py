"""Verify possession and offline reset of original-photo UV/GLB source assets.

This reads existing development fits and does not run SAM or reconstruction.
Filename age labels remain offline research labels; every GLB source_age stays
unknown. Static-object reset is not real aging-service or rendered-continuity
acceptance, and original-photo projection does not detect external occluders.
"""

# Standalone offline entrypoint with existing backend numerical helpers.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import struct
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))
sys.path.insert(0, str(_ROOT / "tools"))

import numpy as np
from age_protocol import _load, _path, _pin
from agemorph3d.age_continuity import static_fallback_at_age, validate_age
from agemorph3d.age_geometry import neutral_vertices, source_frame
from agemorph3d.config import Settings
from agemorph3d.errors import ApiError
from agemorph3d.images import decode_image
from agemorph3d.static_mesh import build_static_mesh
from agemorph3d.tddfa import TddfaResult, _npz_arrays
from agemorph3d.uv_texture import project_photo_texture
from PIL import Image

PROTOCOL_ID = "agemorph3d-source-reset-v1"
UNKNOWN_AGE = {"value": None, "method": "unknown", "calibration_id": None}
_MEDIA = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
_CODE = (
    "tools/source_reset_probe.py",
    "tools/age_protocol.py",
    "backend/src/agemorph3d/age_continuity.py",
    "backend/src/agemorph3d/age_geometry.py",
    "backend/src/agemorph3d/config.py",
    "backend/src/agemorph3d/images.py",
    "backend/src/agemorph3d/static_mesh.py",
    "backend/src/agemorph3d/tddfa.py",
    "backend/src/agemorph3d/uv_texture.py",
    "backend/src/agemorph3d/schemas.py",
    "backend/src/agemorph3d/errors.py",
)


class OriginalAssets(NamedTuple):
    glb: bytes
    png: bytes
    shape: tuple[float, ...]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _verify_plan(root: Path, plan: dict, required: set[Path]) -> None:
    inputs = plan.get("inputs")
    if not isinstance(inputs, dict) or not required <= {_path(root, name) for name in inputs}:
        raise ValueError("Pre-measurement plan must bind every supplied input and source file.")
    for name, pin in inputs.items():
        if set(pin) != {"sha256", "bytes"}:
            raise ValueError("Each plan input must declare SHA-256 and byte size.")
        _pin(root, _path(root, name), pin["sha256"], pin["bytes"])


def _bound_pin(root: Path, plan: dict, pin: dict) -> Path:
    path = _path(root, pin["path"])
    planned = plan["inputs"].get(path.relative_to(root).as_posix())
    if planned != {"sha256": pin["sha256"], "bytes": pin["bytes"]}:
        raise ValueError("Source image, fit and topology pins must be in the frozen plan.")
    _pin(root, path, pin["sha256"], pin["bytes"])
    return path


def load_inputs(args) -> tuple:
    root, plan = args.root, _load(args.study_plan)
    if (
        plan.get("protocol_id") != PROTOCOL_ID
        or type(args.atlas_size) is not int
        or plan.get("atlas_size") != args.atlas_size
        or type(plan.get("expected_sources")) is not int
        or type(plan.get("expected_known_sources")) is not int
        or not 0 <= plan["expected_known_sources"] <= plan["expected_sources"]
        or plan["expected_sources"] < 1
        or not 4 <= args.atlas_size <= 1024
    ):
        raise ValueError("Source-reset plan version and atlas size must match the request.")
    required = {args.protocol_manifest, args.generated_report, args.bfm, args.uv}
    required.update(_path(root, name) for name in _CODE)
    _verify_plan(root, plan, required)
    manifest, generated = _load(args.protocol_manifest), _load(args.generated_report)
    if (
        generated.get("study") != "generated"
        or generated["inputs"]["protocol_manifest"] != _pin(root, args.protocol_manifest)
        or generated["expression_basis"]["asset"] != _pin(root, args.bfm)
    ):
        raise ValueError("Original fits must bind the selected N0 manifest and BFM basis.")
    cases = [case for case in manifest["bridge_cases"] if case["source_status"] == "passed"]
    source_ids = [case["sample_id"] for case in cases]
    if (
        len(set(source_ids)) != len(source_ids)
        or source_ids != plan.get("source_ids")
        or len(cases) != plan.get("expected_sources")
        or any(not re.fullmatch(r"[a-zA-Z0-9_-]+", name) for name in source_ids)
        or any(case["group"] != "development" for case in cases)
    ):
        raise ValueError("The complete source cohort must remain unique development cases.")
    known = 0
    for case in cases:
        age = case["source_age"]
        value = validate_age(age["value"], allow_unknown=True)
        if value is not None:
            if age["method"] != "dataset_filename":
                raise ValueError("Source labels must remain explicitly offline research labels.")
            known += 1
        elif age["method"] != "unknown":
            raise ValueError("Unknown source ages cannot acquire a research or API default.")
    if known != plan.get("expected_known_sources"):
        raise ValueError("Known/unknown source coverage differs from the frozen plan.")
    rows = generated["fit_records"]
    records = {row["sample_id"]: row for row in rows}
    if len(records) != len(rows):
        raise ValueError("Fit records must have unique sample identifiers.")
    topology_pin = generated["topology_artifact"]
    topology = _npz_arrays(
        _bound_pin(root, plan, topology_pin), ("triangles", "keypoint_coordinates")
    )
    basis = _npz_arrays(args.bfm, ("w_exp", "tri", "keypoints"))
    if not np.array_equal(topology["triangles"], basis["tri"]) or not np.array_equal(
        topology["keypoint_coordinates"].reshape(-1), basis["keypoints"].reshape(-1)
    ):
        raise ValueError("Original fitted topology differs from the verified BFM basis.")
    digest = hashlib.sha256(b"agemorph3d:tddfa-topology:v2\0")
    for array in (
        np.array([len(basis["w_exp"]) // 3, len(basis["tri"])], dtype="<i8"),
        basis["tri"].astype("<i8"),
        topology["keypoint_coordinates"].astype("<i8"),
    ):
        digest.update(array.tobytes(order="C"))
    topology_hash = digest.hexdigest()
    binding = _npz_arrays(args.uv, ("uv", "topology_sha256"))
    uv, bound_topology = binding["uv"], binding["topology_sha256"]
    if (
        bound_topology.shape != ()
        or bound_topology.dtype.kind != "U"
        or bound_topology.item() != topology_hash
        or uv.dtype != np.float32
        or uv.shape != (len(basis["w_exp"]) // 3, 2)
        or not np.isfinite(uv).all()
        or np.any(uv < 0)
        or np.any(uv > 1)
    ):
        raise ValueError("Common UV must bind the exact original vertex order and topology.")
    fits = {}
    for case in cases:
        sample_id = case["sample_id"]
        row = records.get(sample_id)
        if (
            row is None
            or row.get("role") != "original"
            or row.get("reference_source_id") != sample_id
            or row.get("subject_id") != case["subject_id"]
            or row.get("source_age") != case["source_age"]["value"]
            or row.get("input") != case["source"]
            or row.get("status") != "ok"
            or row.get("topology_sha256") != topology_hash
        ):
            raise ValueError("Every original source must match its frozen identity, image and fit.")
        _bound_pin(root, plan, case["source"])
        arrays = _npz_arrays(
            _bound_pin(root, plan, row["fit_artifact"]),
            ("vertices", "neutral_vertices", "shape", "expr", "projection", "roi"),
        )
        raw = TddfaResult(
            arrays["shape"],
            arrays["expr"],
            arrays["vertices"],
            basis["tri"],
            arrays["projection"],
            tuple(arrays["roi"].tolist()),
            topology_hash,
        )
        if not np.array_equal(neutral_vertices(raw, basis["w_exp"]), arrays["neutral_vertices"]):
            raise ValueError("Original neutral geometry differs from its expression basis.")
        if row.get("canonical_frame") != source_frame(raw.vertices):
            raise ValueError("Original fit has an inconsistent immutable source frame.")
        fits[sample_id] = raw
    return plan, cases, records, fits, uv


def verify_original_glb(data: bytes, mesh, texture) -> dict:
    """Independently decode transport arrays and the original atlas PNG bytes."""
    magic, version, total = struct.unpack_from("<4sII", data)
    length, kind = struct.unpack_from("<I4s", data, 12)
    binary_length, binary_kind = struct.unpack_from("<I4s", data, 20 + length)
    binary = data[28 + length :]
    if (magic, version, total, kind, binary_kind, binary_length) != (
        b"glTF",
        2,
        len(data),
        b"JSON",
        b"BIN\0",
        len(binary),
    ):
        raise ValueError("Original GLB has an invalid container.")
    document = json.loads(data[20 : 20 + length])
    extras = document["extras"]
    primitive = document["meshes"][0]["primitives"][0]
    if (
        extras["source_age"] != UNKNOWN_AGE
        or extras["asset_mode"] != "static"
        or extras["coordinate_metadata"] != mesh.coordinate_metadata
        or extras["base_texture"] != texture.metadata
        or any("uri" in row for row in document["images"] + document["buffers"])
        or "targets" in primitive
        or document.get("animations")
    ):
        raise ValueError("Original GLB must remain static, self-contained and unknown-age.")
    for accessor_id, expected, dtype in (
        (primitive["attributes"]["POSITION"], mesh.vertices, "<f4"),
        (primitive["attributes"]["NORMAL"], mesh.normals, "<f4"),
        (primitive["attributes"]["TEXCOORD_0"], texture.gltf_uv, "<f4"),
        (primitive["indices"], mesh.triangles, "<u4"),
    ):
        accessor = document["accessors"][accessor_id]
        view = document["bufferViews"][accessor["bufferView"]]
        decoded = np.frombuffer(
            binary,
            dtype=dtype,
            count=expected.size,
            offset=view.get("byteOffset", 0) + accessor.get("byteOffset", 0),
        )
        if not np.array_equal(decoded.reshape(expected.shape), expected):
            raise ValueError("Original GLB changed source geometry, topology or common UV.")
    view = document["bufferViews"][document["images"][0]["bufferView"]]
    png = binary[view["byteOffset"] : view["byteOffset"] + view["byteLength"]]
    if png != texture.png:
        raise ValueError("Original GLB must retain the exact original-photo atlas PNG bytes.")
    with Image.open(io.BytesIO(png)) as image:
        if image.mode != "RGBA" or not np.array_equal(np.asarray(image), texture.rgba):
            raise ValueError("Original GLB changed original-photo atlas pixels.")
    return {"arrays_exact": True, "embedded_png_exact": True, "rgba_exact": True}


def _source(root, output, case, record, fit, uv, atlas_size) -> dict:
    row = {
        "sample_id": case["sample_id"],
        "subject_id": case["subject_id"],
        "group": case["group"],
        "input": case["source"],
        "fit_artifact": record["fit_artifact"],
        "research_source_age": case["source_age"],
        "label_source_age": case["source_age"]["value"],
        "source_age": dict(UNKNOWN_AGE),
        "status": "failed",
        "reset_status": "failed",
    }
    try:
        path = _path(root, case["source"]["path"])
        with decode_image(path.read_bytes(), _MEDIA.get(path.suffix.lower(), ""), Settings()) as im:
            rgb = np.asarray(im).copy()
        if [rgb.shape[1], rgb.shape[0]] != record["image_size"]:
            raise ValueError("Original EXIF-corrected pixels differ from their fitted frame.")
        texture = project_photo_texture(rgb, fit, uv, atlas_size=atlas_size)
        mesh = build_static_mesh(fit, UNKNOWN_AGE, texture=texture)
        roundtrip = verify_original_glb(mesh.glb, mesh, texture)
        original = OriginalAssets(mesh.glb, texture.png, tuple(float(x) for x in fit.shape))
        age = case["source_age"]["value"]
        if age is None:
            try:
                static_fallback_at_age(original, None, 20)
            except ValueError:
                reset = {"status": "unavailable", "error_code": "SOURCE_AGE_UNKNOWN"}
            else:
                raise ValueError("Unknown source age unexpectedly admitted an absolute request.")
        else:
            restored = static_fallback_at_age(original, age, age)
            reset = {
                "status": "ok",
                "target_research_label": age,
                "object_identity": restored is original,
                "glb_bytes_exact": restored.glb == original.glb,
                "png_bytes_exact": restored.png == original.png,
                "shape_coefficients_exact": restored.shape == original.shape,
            }
            if not all(
                reset[key]
                for key in (
                    "object_identity",
                    "glb_bytes_exact",
                    "png_bytes_exact",
                    "shape_coefficients_exact",
                )
            ):
                raise ValueError("Offline source reset did not retain the immutable original.")
        directory = output / case["sample_id"]
        directory.mkdir()
        artifacts = {}
        for key, name, data in (
            ("atlas", "original.png", texture.png),
            ("glb", "original.glb", mesh.glb),
        ):
            artifact = directory / name
            with artifact.open("xb") as stream:
                stream.write(data)
            artifacts[key] = _pin(root, artifact)
        row.update(
            status="ok",
            reset=reset,
            artifacts=artifacts,
            glb_roundtrip=roundtrip,
            reset_status="passed" if age is not None else "source_age_unknown",
            byte_equality={
                key: reset.get(key)
                for key in ("glb_bytes_exact", "png_bytes_exact", "shape_coefficients_exact")
            },
            texture_metadata=texture.metadata,
            source_frame=mesh.coordinate_metadata,
            shape_coefficients=list(original.shape),
            shape_float64_sha256=_digest(np.asarray(original.shape, dtype="<f8").tobytes()),
            rgba_sha256=_digest(texture.rgba.tobytes()),
            external_occlusion_reviewed=False,
        )
    except (OSError, ValueError, KeyError, TypeError, ApiError) as error:
        row.update(
            error_code="SOURCE_ASSET_FAILED", error_type=type(error).__name__, detail=str(error)
        )
    return row


def run(args) -> dict:
    if args.output_dir.exists():
        raise ValueError("Output directory must not already exist.")
    plan, cases, records, fits, uv = load_inputs(args)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    results = []
    for case in cases:
        results.append(
            _source(
                args.root,
                args.output_dir,
                case,
                records[case["sample_id"]],
                fits[case["sample_id"]],
                uv,
                args.atlas_size,
            )
        )
        print(
            f"source {len(results)}/{len(cases)}: {case['sample_id']} {results[-1]['status']}",
            flush=True,
        )
    _verify_plan(args.root, plan, set())
    successful = [row for row in results if row["status"] == "ok"]
    exact = [row for row in successful if row["reset"]["status"] == "ok"]
    unavailable = [row for row in successful if row["reset"]["status"] == "unavailable"]
    report = {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "scope": "original-photo source assets and offline static-object exact reset only",
        "research_only": True,
        "source_age_api_policy": "unknown",
        "service_ready": False,
        "g3_complete": False,
        "production_source_reset_accepted": False,
        "rendered_continuity_accepted": False,
        "age_texture_quality_accepted": False,
        "identity_quality_accepted": False,
        "new_model_inference": False,
        "holdout_age_results_opened": False,
        "inputs": {
            name: _pin(args.root, getattr(args, name))
            for name in ("study_plan", "protocol_manifest", "generated_report", "bfm", "uv")
        },
        "records": results,
        "retained_prior_original_fit_failures": [
            row for row in records.values() if row["role"] == "original" and row["status"] != "ok"
        ],
        "summary": {
            "requested_sources": len(cases),
            "source_asset_statuses": dict(Counter(row["status"] for row in results)),
            "original_source_assets_built": len(successful),
            "assets_created": len(successful),
            "offline_exact_resets": len(exact),
            "known_label_resets_passed": len(exact),
            "unknown_source_resets_unavailable": len(unavailable),
            "unknown_age_rejected": len(unavailable),
            "failed_sources": len(cases) - len(successful),
            "all_known_offline_resets_passed": len(exact) == plan["expected_known_sources"],
            "all_requested_original_assets_built": len(successful) == len(cases),
        },
        "limitations": [
            "Filename ages are offline research labels, never API user/estimated source ages.",
            "Unknown ages remain unknown; their original assets do not authorize absolute ages.",
            "Newly built original-photo UV is not an independently signed-off source texture.",
            "External occlusion, visual seams, age/identity quality and rendered reset "
            "are unaccepted.",
            "Static object byte identity is not an integrated aging-service reset test.",
        ],
    }
    with (args.output_dir / "report.json").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument("--study-plan", required=True)
    parser.add_argument(
        "--protocol-manifest",
        default="output/research/age-protocol-20261020/verified/manifest.json",
    )
    parser.add_argument(
        "--generated-report", default="output/research/age-stage2-20261020/generated/report.json"
    )
    parser.add_argument("--bfm", default="data/models/3ddfa-v2/bfm.npz")
    parser.add_argument("--uv", default="output/backend/b45/combined-real/uv_bound.npz")
    parser.add_argument("--atlas-size", type=int, default=256)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    try:
        for key in (
            "study_plan",
            "protocol_manifest",
            "generated_report",
            "bfm",
            "uv",
            "output_dir",
        ):
            setattr(args, key, _path(args.root, getattr(args, key)))
        report = run(args)
    except (OSError, ValueError, KeyError, TypeError, ApiError) as error:
        print(f"source-reset probe rejected: {error}", file=sys.stderr)
        return 2
    return 0 if report["summary"]["all_requested_original_assets_built"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

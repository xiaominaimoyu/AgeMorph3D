"""Offline target-own projection into shared UV on unchanged source geometry.

Generated pixels and conservative reviewed exclusions are research evidence,
not observed photos, independent segmentation truth or accepted age capability.
"""

# Standalone offline entrypoint; existing numeric helpers never run inference here.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import struct
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))
sys.path.insert(0, str(_ROOT / "tools"))

import numpy as np
from age_protocol import _load, _path, _pin
from age_refit_probe import _write_csv
from age_route_probe import _load_study, _verify_descendants
from agemorph3d.static_mesh import _encode_glb, build_static_mesh
from agemorph3d.target_uv import (
    register_generated_texture,
    texture_boundary_diagnostics,
)
from agemorph3d.tddfa import _npz_arrays
from agemorph3d.uv_texture import UV_REASON_CODES
from PIL import Image

UNKNOWN_AGE = {"value": None, "method": "unknown", "calibration_id": None}
_UV_SHA256 = "7e412e7e1f7337816db7175c2db0020854b9a77292e7582763e9d45b06e3ad7b"
_COLORS = np.array(
    [
        [20, 25, 32],
        [230, 80, 210],
        [80, 105, 145],
        [240, 160, 70],
        [110, 65, 180],
        [245, 80, 80],
        [65, 205, 140],
    ],
    dtype=np.uint8,
)


def _array_hash(array: np.ndarray, dtype: str) -> str:
    return hashlib.sha256(np.asarray(array, dtype=dtype).tobytes(order="C")).hexdigest()


def _mask(root: Path, pin: dict, image_size: list[int]) -> np.ndarray:
    path = _path(root, pin["path"])
    _pin(root, path, pin["sha256"], pin["bytes"])
    with Image.open(path) as image:
        if image.format != "PNG" or image.mode != "L" or list(image.size) != image_size:
            raise ValueError("Target masks must be grayscale PNGs in the target pixel frame.")
        pixels = np.asarray(image).copy()
    if not np.all((pixels == 0) | (pixels == 255)):
        raise ValueError("Target eligibility and occluder masks must contain only 0/255.")
    return pixels == 255


def validate_mask_review(root: Path, review: dict, jobs: dict, records: dict) -> dict:
    """Reject missing, reassigned or inconsistent target-local mask evidence."""
    rows = {row["sample_id"]: row for row in review["target_records"]}
    if len(rows) != len(review["target_records"]) or set(rows) != set(jobs):
        raise ValueError("Mask review must contain every unique generated target exactly once.")
    result = {}
    for sample_id, job in jobs.items():
        row = rows[sample_id]
        notes = row.get("notes")
        notes_valid = (isinstance(notes, str) and bool(notes.strip())) or (
            isinstance(notes, list)
            and bool(notes)
            and all(isinstance(note, str) and bool(note.strip()) for note in notes)
        )
        if (
            row["input"] != job["input"]
            or row.get("target_fit") != records[sample_id].get("fit_artifact")
            or row["status"] != "reviewed_conservative_exclusion"
            or row["reviewer"] != "codex_visual_review"
            or not isinstance(row.get("method"), str)
            or not row["method"].strip()
            or not notes_valid
        ):
            raise ValueError("Reviewed masks must bind this target input and review method.")
        size = records[sample_id].get("image_size")
        if not size or len(size) != 2 or any(type(x) is not int or x < 1 for x in size):
            raise ValueError("Target image size is unavailable for mask association.")
        allowed = _mask(root, row["allowed_mask"], size)
        occluded = _mask(root, row["occluded_mask"], size)
        if np.any(allowed & occluded):
            raise ValueError("A reviewed occluder candidate cannot be an allowed sample pixel.")
        for key, count in (
            ("allowed_pixels", int(allowed.sum())),
            ("excluded_occluder_pixels", int(occluded.sum())),
        ):
            if type(row[key]) is not int or row[key] != count:
                raise ValueError("Reviewed mask counts differ from their actual pixel arrays.")
        result[sample_id] = (row, allowed, occluded)
    return result


def _parse_glb(data: bytes) -> tuple[dict, bytes]:
    if len(data) < 28:
        raise ValueError("Truncated GLB.")
    magic, version, total = struct.unpack_from("<4sII", data)
    length, kind = struct.unpack_from("<I4s", data, 12)
    if (
        magic != b"glTF"
        or version != 2
        or total != len(data)
        or kind != b"JSON"
        or length % 4
        or 28 + length > len(data)
    ):
        raise ValueError("Invalid GLB container header.")
    binary_length, binary_kind = struct.unpack_from("<I4s", data, 20 + length)
    binary = data[28 + length :]
    if binary_kind != b"BIN\0" or binary_length != len(binary):
        raise ValueError("Invalid GLB binary chunk.")
    return json.loads(data[20 : 20 + length]), binary


def _generated_names(data: bytes) -> bytes:
    """Rename research material without changing embedded geometry or texture bytes."""
    document, binary = _parse_glb(data)
    document["materials"][0]["name"] = "Registered_Generated_Surface"
    encoded = json.dumps(
        document, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    encoded += b" " * ((-len(encoded)) % 4)
    return (
        struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary))
        + struct.pack("<I4s", len(encoded), b"JSON")
        + encoded
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )


def verify_glb(data: bytes, base, texture, research: dict) -> dict:
    """Decode all transport arrays and PNG, preserving source frame and unknown alpha."""
    document, binary = _parse_glb(data)
    if (
        any("uri" in row for row in document["buffers"] + document["images"])
        or document["buffers"] != [{"byteLength": len(binary)}]
        or document["materials"][0]["alphaMode"] != "MASK"
        or document["materials"][0]["alphaCutoff"] != 0.5
        or document["samplers"][0]["wrapS"] != 33071
        or document["samplers"][0]["wrapT"] != 33071
    ):
        raise ValueError("GLB must be self-contained with MASK alpha and clamped sampling.")
    primitive = document["meshes"][0]["primitives"][0]
    if "targets" in primitive or document.get("animations"):
        raise ValueError("Registered generated texture is a static geometry research asset.")
    for attribute, accessor_id, expected, dtype, component_type in (
        ("POSITION", primitive["attributes"]["POSITION"], base.vertices, "<f4", 5126),
        ("NORMAL", primitive["attributes"]["NORMAL"], base.normals, "<f4", 5126),
        (
            "TEXCOORD_0",
            primitive["attributes"]["TEXCOORD_0"],
            texture.gltf_uv,
            "<f4",
            5126,
        ),
        ("indices", primitive["indices"], base.triangles.reshape(-1), "<u4", 5125),
    ):
        accessor = document["accessors"][accessor_id]
        view = document["bufferViews"][accessor["bufferView"]]
        if accessor["componentType"] != component_type or accessor["count"] != len(expected):
            raise ValueError("GLB accessor differs from the verified source or common UV.")
        decoded = np.frombuffer(
            binary,
            dtype=dtype,
            count=expected.size,
            offset=view.get("byteOffset", 0) + accessor.get("byteOffset", 0),
        )
        if not np.array_equal(decoded.reshape(expected.shape), expected):
            raise ValueError(f"GLB {attribute} differs from unchanged source geometry/common UV.")
    image = document["images"][0]
    view = document["bufferViews"][image["bufferView"]]
    png = binary[view["byteOffset"] : view["byteOffset"] + view["byteLength"]]
    if image["mimeType"] != "image/png" or png != texture.png:
        raise ValueError("GLB must preserve the exact registered atlas PNG.")
    with Image.open(io.BytesIO(png)) as decoded:
        if decoded.mode != "RGBA" or not np.array_equal(np.asarray(decoded), texture.rgba):
            raise ValueError("GLB atlas RGBA or alpha did not roundtrip.")
    extras = document["extras"]
    if (
        extras["source_age"] != UNKNOWN_AGE
        or extras["asset_mode"] != "static"
        or extras["coordinate_metadata"] != base.coordinate_metadata
        or extras["registered_target_texture"] != research
    ):
        raise ValueError("Static source age, frame or generated-texture provenance changed.")
    return {
        "self_contained": True,
        "positions_equal_source": True,
        "normals_equal_source": True,
        "ordered_indices_equal_source": True,
        "uv_equal_common_atlas": True,
        "embedded_png_bytes_equal": True,
        "decoded_rgba_equal": True,
        "mask_alpha_and_clamp": True,
        "generated_provenance_preserved": True,
        "vertices": len(base.vertices),
        "triangles": len(base.triangles),
    }


def _write_bytes(path: Path, data: bytes, owned: list[Path]) -> None:
    with path.open("xb") as stream:
        owned.append(path)
        stream.write(data)


def _png(array: np.ndarray) -> bytes:
    output = io.BytesIO()
    Image.fromarray(array).save(output, "PNG")
    return output.getvalue()


def _target(
    root,
    output,
    job,
    record,
    source,
    target,
    uv,
    uv_pin,
    masks,
    atlas_size,
    base,
    owned,
    source_error=None,
) -> dict:
    sample_id, source_id = job["sample_id"], job["reference_source_id"]
    row = {
        "sample_id": sample_id,
        "source_id": source_id,
        "subject_id": job["subject_id"],
        "source_age_label": job["source_age"],
        "target_age": job["target_age"],
        "status": "failed",
        "input": job["input"],
        "target_fit": record.get("fit_artifact"),
    }
    if source is None or target is None:
        row["error_code"] = "SOURCE_OR_TARGET_FIT_UNAVAILABLE"
        return row
    if source_error is not None:
        row.update(error_code="SOURCE_STATIC_GEOMETRY_FAILED", **source_error)
        return row
    review, allowed, occluded = masks
    row["mask_review"] = review
    directory = output / sample_id
    directory.mkdir()
    local_owned = []
    try:
        with Image.open(_path(root, job["input"]["path"])) as image:
            if image.format != "PNG" or list(image.size) != record["image_size"]:
                raise ValueError("Generated target image dimensions differ from its fit.")
            rgb = np.asarray(image.convert("RGB")).copy()
        texture = register_generated_texture(rgb, target, uv, allowed, atlas_size=atlas_size)
        diagnostics = texture_boundary_diagnostics(texture, uv, source.triangles)
        classification = texture.classification
        if (
            classification is None
            or classification.dtype != np.uint8
            or classification.shape != (atlas_size, atlas_size)
            or not np.isin(classification, list(UV_REASON_CODES.values())).all()
            or not np.array_equal(texture.coverage, classification == UV_REASON_CODES["sampled"])
            or not diagnostics["alpha_coverage_matches"]
            or not diagnostics["unknown_rgba_zero"]
            or diagnostics["nonbinary_alpha_texels"]
        ):
            raise ValueError("UV classification/alpha partition or unknown RGBA invariant failed.")
        research = {
            "kind": "sam_generated_registered_uv",
            "source_id": source_id,
            "target_sample_id": sample_id,
            "target_age_condition": job["target_age"],
            "source_age_label": job["source_age"],
            "common_uv_sha256": uv_pin["sha256"],
            "target_image_sha256": job["input"]["sha256"],
            "target_fit_sha256": record["fit_artifact"]["sha256"],
            "target_allowed_mask_sha256": review["allowed_mask"]["sha256"],
            "age_quality_accepted": False,
            "identity_quality_accepted": False,
            "mask_review_scope": "conservative exclusions, not segmentation ground truth",
        }
        extras = _parse_glb(base.glb)[0]["extras"]
        extras.update(registered_target_texture=research, base_texture=texture.metadata)
        glb = _generated_names(
            _encode_glb(base.vertices, base.normals, base.triangles, extras, texture)
        )
        roundtrip = verify_glb(glb, base, texture, research)
        samples = io.BytesIO()
        np.savez_compressed(
            samples,
            rgba=texture.rgba,
            classification=classification,
            coverage=texture.coverage,
            gltf_uv=texture.gltf_uv,
        )
        payloads = {
            "atlas": ("atlas.png", texture.png),
            "classification": ("classification.png", _png(classification)),
            "coverage": ("coverage.png", _png(texture.coverage.astype(np.uint8) * 255)),
            "classification_preview": (
                "classification-preview.png",
                _png(_COLORS[classification]),
            ),
            "samples": ("samples.npz", samples.getvalue()),
            "glb": ("mesh.glb", glb),
        }
        artifacts = {}
        for key, (name, data) in payloads.items():
            path = directory / name
            _write_bytes(path, data, local_owned)
            artifacts[key] = _pin(root, path)
        row.update(
            status="ok",
            artifacts=artifacts,
            asset_mode="static",
            source_age=UNKNOWN_AGE,
            capabilities={"age_morph": False, "age_texture": False},
            texture_url=None,
            common_uv=uv_pin,
            sampling_geometry="target_full_identity_expression_raw_fit",
            projection=target.projection.tolist(),
            roi=list(target.roi),
            source_frame=base.coordinate_metadata,
            source_positions_sha256=_array_hash(base.vertices, "<f4"),
            source_normals_sha256=_array_hash(base.normals, "<f4"),
            source_indices_sha256=_array_hash(base.triangles, "<u4"),
            gltf_uv_sha256=_array_hash(texture.gltf_uv, "<f4"),
            texture_metadata=texture.metadata,
            boundary_diagnostics=diagnostics,
            target_review_allowed_pixels=int(allowed.sum()),
            target_review_occluder_candidate_pixels=int(occluded.sum()),
            glb_roundtrip=roundtrip,
            age_texture_quality_accepted=False,
            identity_quality_accepted=False,
            research_only=True,
        )
        result_path = directory / "result.json"
        _write_bytes(
            result_path,
            (json.dumps(row, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8"),
            local_owned,
        )
        row["artifacts"]["result"] = _pin(root, result_path)
        owned.extend(local_owned)
        return row
    except (OSError, ValueError, KeyError, TypeError) as error:
        for path in local_owned:
            path.unlink(missing_ok=True)
        row.pop("artifacts", None)
        row.update(
            status="failed",
            error_code="TARGET_REGISTRATION_FAILED",
            error_type=type(error).__name__,
            detail=str(error),
        )
        return row


def load_inputs(args) -> tuple:
    root = args.root
    protocol, plan = _load(args.protocol), _load(args.study_plan)
    if (
        protocol["protocol_id"] != "agemorph3d-target-uv-v1"
        or plan["protocol_id"] != protocol["protocol_id"]
    ):
        raise ValueError("UV protocol and pre-projection plan must use the same supported version.")
    required = {
        args.protocol,
        args.mask_review,
        args.protocol_manifest,
        args.generated_report,
        args.selection,
        args.bfm,
        args.uv,
    }
    if not required <= {_path(root, name) for name in plan["inputs"]}:
        raise ValueError("Pre-projection study plan must bind every supplied input path.")
    for name, pin in plan["inputs"].items():
        _pin(root, _path(root, name), pin["sha256"], pin["bytes"])
    manifest, generated = _load(args.protocol_manifest), _load(args.generated_report)
    review, selection = _load(args.mask_review), _load(args.selection)
    if (
        protocol["parent_protocol_id"] != manifest["protocol_id"]
        or review["protocol_id"] != protocol["protocol_id"]
        or review["schema_version"] != 1
        or generated["inputs"]["protocol_manifest"] != _pin(root, args.protocol_manifest)
        or selection["research_route_choice"] != "static_fallback"
        or selection["production_route_selected"] is not None
    ):
        raise ValueError("Inputs must preserve N0 identity uses and the N3 static fallback.")
    _verify_descendants(root, manifest)
    _verify_descendants(root, generated)
    _verify_descendants(root, review)
    bfm_pin = _pin(root, args.bfm)
    if generated["expression_basis"]["asset"] != bfm_pin:
        raise ValueError("Generated fits and common UV must use the same verified BFM asset.")
    basis = _npz_arrays(args.bfm, ("w_exp", "tri", "keypoints"))
    jobs, records, fits, _ = _load_study(root, generated, manifest, "generated", basis)
    targets = {key: job for key, job in jobs.items() if job["role"] == "sam_generated"}
    if (
        len(targets) != protocol["expected_generated_images"]
        or len({job["reference_source_id"] for job in targets.values()})
        != protocol["expected_source_images"]
    ):
        raise ValueError("Generated UV cohort differs from the complete frozen target set.")
    uv_pin = _pin(root, args.uv, args.uv_sha256)
    binding = _npz_arrays(args.uv, ("uv", "topology_sha256"))
    uv, topology = binding["uv"], binding["topology_sha256"]
    if (
        topology.shape != ()
        or topology.dtype.kind != "U"
        or uv.dtype != np.float32
        or uv.shape != (len(basis["w_exp"]) // 3, 2)
        or not np.isfinite(uv).all()
        or np.any(uv < 0)
        or np.any(uv > 1)
        or any(raw.topology_sha256 != topology.item() for raw in fits.values())
    ):
        raise ValueError(
            "Bound UV order, vertex count, range or topology differs from fitted data."
        )
    masks = validate_mask_review(root, review, targets, records)
    return protocol, generated, targets, records, fits, uv, uv_pin, masks


def _contact_html(records: list[dict]) -> str:
    cards = []
    for row in records:
        name = html.escape(row["sample_id"], quote=True)
        if row["status"] != "ok":
            cards.append(f"<article><h2>{name}</h2><p>Registration failed.</p></article>")
            continue
        cards.append(
            f'<article><h2>{name}</h2><img src="{name}/atlas.png" alt="Generated UV atlas">'
            f'<img src="{name}/classification-preview.png" alt="UV classification">'
            f'<p><a href="{name}/mesh.glb">Static source GLB</a> · '
            f'<a href="{name}/result.json">Evidence</a></p></article>'
        )
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>N4 UV research</title>'
        "<style>body{font:16px system-ui;background:#17212b;color:#edf3f8;margin:30px}"
        ".cards{display:flex;flex-wrap:wrap;gap:20px}article{padding:14px;background:#243342;"
        "border-radius:10px}h2{font-size:16px}img{width:256px;background:repeating-conic-gradient("
        "#ddd 0 25%,#999 0 50%) 0/20px 20px}a{color:#8ddccc}</style>"
        "<h1>共同 UV 注册：生成纹理研究</h1><p>采样使用各目标自身完整拟合与投影；"
        "模型保持原始源静态几何。透明区不填充；人工保守遮挡排除不等于分割真值。"
        "绿色为采样生成像素，红色为目标mask排除，其余色为几何未知原因。"
        '年龄效果、身份保持、视觉接缝和生产服务均未在此验收。</p><div class="cards">'
        + "".join(cards)
        + "</div></html>"
    )


def run(args) -> dict:
    protocol, generated, jobs, records, fits, uv, uv_pin, masks = load_inputs(args)
    output, owned, results, bases, source_errors = args.output_dir, [], [], {}, {}
    output.mkdir(parents=True, exist_ok=False)
    try:
        for sample_id, job in jobs.items():
            source_id = job["reference_source_id"]
            source = fits.get(source_id)
            if source is not None and source_id not in bases and source_id not in source_errors:
                try:
                    bases[source_id] = build_static_mesh(source, UNKNOWN_AGE)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    source_errors[source_id] = {
                        "error_type": type(error).__name__,
                        "detail": str(error),
                    }
            results.append(
                _target(
                    args.root,
                    output,
                    job,
                    records[sample_id],
                    source,
                    fits.get(sample_id),
                    uv,
                    uv_pin,
                    masks[sample_id],
                    protocol["atlas_size"],
                    bases.get(source_id),
                    owned,
                    source_error=source_errors.get(source_id),
                )
            )
            print(
                f"registered {len(results)}/{len(jobs)}: {sample_id} {results[-1]['status']}",
                flush=True,
            )
        invariants = {}
        for row in results:
            if row["status"] != "ok":
                continue
            key = row["source_id"]
            hashes = {
                name: row[name]
                for name in (
                    "source_positions_sha256",
                    "source_normals_sha256",
                    "source_indices_sha256",
                    "gltf_uv_sha256",
                )
            }
            if invariants.setdefault(key, hashes) != hashes:
                raise ValueError("Different targets changed source geometry or common UV order.")
        successful = [row for row in results if row["status"] == "ok"]
        successful_roundtrips = bool(successful) and all(
            row["glb_roundtrip"]["decoded_rgba_equal"] for row in successful
        )
        report = {
            "schema_version": 1,
            "recorded_at_utc": datetime.now(UTC).isoformat(),
            "protocol_id": protocol["protocol_id"],
            "research_only": True,
            "service_ready": False,
            "g3_complete": False,
            "years_calibrated": False,
            "age_texture_quality_accepted": False,
            "identity_quality_accepted": False,
            "visual_seam_quality_accepted": False,
            "independent_segmentation_ground_truth": False,
            "automatic_external_occlusion_detection": False,
            "holdout_age_results_opened": False,
            "new_sam_inference": False,
            "training": False,
            "inputs": {
                name: _pin(args.root, getattr(args, name))
                for name in (
                    "protocol",
                    "study_plan",
                    "mask_review",
                    "protocol_manifest",
                    "generated_report",
                    "selection",
                    "bfm",
                    "uv",
                )
            },
            "records": results,
            "source_geometry_invariants": invariants,
            "retained_prior_fit_failures": [
                row for row in generated["fit_records"] if row["status"] != "ok"
            ],
            "classification_codes": UV_REASON_CODES,
            "summary": {
                "requested_targets": len(jobs),
                "sources": len(bases),
                "statuses": dict(Counter(row["status"] for row in results)),
                "all_successful_glb_arrays_and_rgba_roundtripped": successful_roundtrips,
                "all_requested_glb_roundtrips_passed": (
                    successful_roundtrips and len(successful) == len(jobs)
                ),
            },
        }
        _write_bytes(output / "contact.html", _contact_html(results).encode("utf-8"), owned)
        _write_csv(
            output / "targets.csv",
            results,
            [
                "sample_id",
                "source_id",
                "subject_id",
                "source_age_label",
                "target_age",
                "status",
                "error_code",
                "source_positions_sha256",
                "gltf_uv_sha256",
            ],
        )
        owned.append(output / "targets.csv")
        report["output_artifacts"] = {
            path.name: _pin(args.root, path) for path in owned if path.parent == output
        }
        _write_bytes(
            output / "report.json",
            (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode(
                "utf-8"
            ),
            owned,
        )
        return report
    except (OSError, ValueError, KeyError, TypeError):
        for path in owned:
            path.unlink(missing_ok=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument("--protocol", default="docs/uv-registration-v1.json")
    parser.add_argument(
        "--protocol-manifest",
        default="output/research/age-protocol-20261020/verified/manifest.json",
    )
    parser.add_argument(
        "--generated-report",
        default="output/research/age-stage2-20261020/generated/report.json",
    )
    parser.add_argument(
        "--selection",
        default="output/research/age-stage3-20261021/comparison-final/selection.json",
    )
    parser.add_argument(
        "--study-plan", default="output/research/age-stage4-20261021/study-plan.json"
    )
    parser.add_argument(
        "--mask-review", default="output/research/age-stage4-20261021/mask-review.json"
    )
    parser.add_argument("--bfm", default="data/models/3ddfa-v2/bfm.npz")
    parser.add_argument("--uv", default="output/backend/b45/combined-real/uv_bound.npz")
    parser.add_argument("--uv-sha256", default=_UV_SHA256)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    try:
        for name in (
            "protocol",
            "protocol_manifest",
            "generated_report",
            "selection",
            "study_plan",
            "mask_review",
            "bfm",
            "uv",
            "output_dir",
        ):
            setattr(args, name, _path(args.root, getattr(args, name)))
        if args.output_dir.exists():
            raise FileExistsError(
                "Output directory already exists; existing evidence is preserved."
            )
        report = run(args)
        print(json.dumps(report["summary"], ensure_ascii=True))
        return 0 if all(row["status"] == "ok" for row in report["records"]) else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"{type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

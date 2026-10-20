"""Offline development-only longitudinal and generated-image refitting research.

Each image gets its own detector, 3DDFA projection and expression estimate. All
comparisons share the unchanged original source frame; this does not enable age
services, establish year calibration or prove identity/3D ground-truth accuracy.
"""

# The standalone entrypoint resolves its existing backend/tool import directories.
# ruff: noqa: E402

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

_ROOT = Path(__file__).resolve().parents[1]
_BACKEND_SRC = _ROOT / "backend" / "src"
_TOOLS_SRC = _ROOT / "tools"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))
if str(_TOOLS_SRC) not in sys.path:
    sys.path.insert(0, str(_TOOLS_SRC))

import numpy as np
from age_protocol import _hash, _load, _path, _pin, build_manifest
from agemorph3d.age_geometry import compare_fits, neutral_vertices, source_frame
from agemorph3d.age_statistics import aggregate_identity_metrics, longitudinal_pairs
from agemorph3d.config import Settings
from agemorph3d.errors import ApiError
from agemorph3d.images import decode_image
from agemorph3d.model_assets import ModelAssetError, load_verified_manifest
from agemorph3d.model_lifecycle import _dispose, detector_selftest, reconstructor_selftest
from agemorph3d.static_mesh import projection_rotation
from agemorph3d.static_probe import _construct_model
from agemorph3d.tddfa import _npz_arrays, project_vertices

_BACKENDS = {"detector": "yolov5_face_onnx", "reconstructor": "3ddfa_v2_onnx"}
_MEDIA = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
_METRICS = [
    "neutral_rms",
    "neutral_max",
    "full_rms",
    "full_max",
    "expression_delta_rms",
    "expression_coeff_l2",
    "shape_coeff_l2",
    "pose_rotation_delta_degrees",
]


def _write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n")


def _write_csv(path: Path, records: list[dict], columns: list[str]) -> None:
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)


def _verified_protocol(root: Path, manifest_path: Path, freeze_path: Path) -> dict:
    """Rebuild the exact N0 snapshot before any model loading or result viewing."""
    manifest = _load(manifest_path)
    inputs = manifest["inputs"]
    generated_controls = {
        _path(root, case["same_age_control"]["report"]["path"]).parent.parent
        for case in manifest["bridge_cases"]
        if case["same_age_control"]["status"] == "generated"
    }
    if len(generated_controls) > 1:
        raise ValueError("Same-age controls do not share the frozen evidence directory.")
    controls = next(
        iter(generated_controls), root / "output/research/age-protocol-20261020/same-age"
    )
    rebuilt = build_manifest(
        root,
        _path(root, inputs["protocol"]["path"]),
        _path(root, inputs["adult_subset"]["path"]),
        _path(root, inputs["bridge_report"]["path"]),
        controls,
        freeze_path,
    )
    if rebuilt != manifest or not rebuilt["summary"]["same_age_controls_complete"]:
        raise ValueError("N0 manifest differs from its frozen inputs and identity uses.")
    return manifest


def _jobs(manifest: dict, study: str) -> list[dict]:
    jobs = []
    if study == "longitudinal":
        for image in manifest["adult_images"]:
            if image["group"] == "development":
                jobs.append(
                    {
                        "sample_id": "fgnet-" + Path(image["path"]).stem.lower(),
                        "subject_id": image["subject_id"],
                        "source_age": image["source_age"],
                        "role": "original",
                        "input": {key: image[key] for key in ("path", "sha256", "bytes")},
                    }
                )
    else:
        for case in manifest["bridge_cases"]:
            common = {
                "subject_id": case["subject_id"],
                "source_age": case["source_age"]["value"],
                "reference_source_id": case["sample_id"],
            }
            jobs.append(
                dict(common, sample_id=case["sample_id"], role="original", input=case["source"])
            )
            if case["source_status"] != "passed":
                continue
            jobs.append(
                dict(
                    common,
                    sample_id=case["sample_id"] + "--aligned",
                    role="aligned_source",
                    input=case["artifacts"]["aligned.png"],
                )
            )
            runs = {run["target_age"]: run for run in case["target_runs"]}
            control = case["same_age_control"]
            if control["status"] in ("generated", "reused_existing"):
                runs[control["target_age"]] = control["output"]
            for age, pin in sorted(runs.items()):
                jobs.append(
                    dict(
                        common,
                        sample_id=f"{case['sample_id']}--sam-{age:03d}",
                        role="sam_generated",
                        target_age=age,
                        is_same_age=age == common["source_age"],
                        input={key: pin[key] for key in ("path", "sha256", "bytes")},
                    )
                )
    identifiers = [job["sample_id"] for job in jobs]
    if len(set(identifiers)) != len(jobs) or any(
        not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,120}", name) for name in identifiers
    ):
        raise ValueError("Fit sample identifiers must be safe and unique.")
    return jobs


def _load_models(args, manifest: dict, report: dict, owned: dict) -> np.ndarray:
    root = args.root
    historical = [
        _load(_path(root, case["bridge_report"]["path"])) for case in manifest["bridge_cases"]
    ]
    expression_basis = None
    for role, path in (
        ("detector", args.detector_manifest),
        ("reconstructor", args.reconstructor_manifest),
    ):
        digest = _hash(path)
        if any(old["models"][role]["manifest_sha256"] != digest for old in historical):
            raise ModelAssetError("Current model differs from frozen source reconstruction.")
        assets = load_verified_manifest(
            path, research_allow_unresolved=args.research_allow_unresolved
        )
        if assets.manifest.backend != _BACKENDS[role] or _hash(path) != digest:
            raise ModelAssetError("Model role or manifest changed during verification.")
        model = _construct_model(role, assets)
        owned[role] = model
        if (
            model.provider != "CPUExecutionProvider"
            or model.license_verified != assets.license_verified
        ):
            raise ModelAssetError("Unexpected model provider or permission state.")
        (detector_selftest if role == "detector" else reconstructor_selftest)(model)
        report["models"][role] = {
            "model_id": assets.manifest.model_id,
            "backend": assets.manifest.backend,
            "manifest_sha256": digest,
            "manifest": _pin(root, path, digest),
            "license_verified": assets.license_verified,
            "provider": model.provider,
            "operator_selftest": "passed",
            "artifacts": [
                _pin(root, Path(assets.paths[item.role]), item.sha256, item.size_bytes)
                for item in assets.manifest.artifacts
            ],
        }
        if role == "reconstructor":
            basis_path = Path(assets.paths["bfm"])
            arrays = _npz_arrays(basis_path, ("u", "w_shp", "w_exp"))
            expression_basis = np.asarray(arrays["w_exp"], dtype=np.float64)
            if (
                expression_basis.ndim != 2
                or expression_basis.shape[1] < 10
                or not np.isfinite(expression_basis).all()
            ):
                raise ModelAssetError("Verified BFM expression basis is invalid.")
            expression_basis = expression_basis[:, :10].copy()
            report["expression_basis"] = {
                "asset": _pin(root, basis_path),
                "shape": list(expression_basis.shape),
                "unit": "same verified raw BFM coordinates as fitted vertices",
            }
            expected = {
                old["reconstruction"]["topology_sha256"]
                for old in historical
                if old["technical_execution"] == "passed"
            }
            if expected != {model.topology_sha256}:
                raise ModelAssetError("Topology differs from the frozen bridge model.")
    return expression_basis


def _fit_one(
    root: Path, job: dict, models: dict, basis: np.ndarray, output: Path
) -> tuple[dict, object | None]:
    record = dict(job, status="failed", error_code=None)
    stage = "hash"
    started = perf_counter()
    try:
        path = _path(root, job["input"]["path"])
        _pin(root, path, job["input"]["sha256"], job["input"]["bytes"])
        stage = "input"
        settings = Settings()
        if path.stat().st_size > settings.max_image_bytes:
            raise ApiError(413, "INPUT_TOO_LARGE", "Input exceeds bounded research image size.")
        data = path.read_bytes()
        with decode_image(data, _MEDIA.get(path.suffix.lower(), ""), settings) as image:
            rgb = np.asarray(image).copy()
        record["image_size"] = [int(rgb.shape[1]), int(rgb.shape[0])]
        stage = "detection"
        faces = models["detector"].detect(rgb)
        if not isinstance(faces, list):
            raise ValueError("Invalid detector output.")
        record["face_count"] = len(faces)
        if len(faces) != 1:
            raise ApiError(422, "NO_FACE" if not faces else "MULTI_FACE", "Single face required.")
        stage = "reconstruction"
        model = models["reconstructor"]
        raw = model.reconstruct(rgb, faces[0].bbox)
        if raw.topology_sha256 != model.topology_sha256 or not np.array_equal(
            raw.triangles, model.triangles
        ):
            raise ValueError("Model or ordered topology mismatch.")
        stage = "pose"
        rotation, decomposition = projection_rotation(raw.projection)
        stage = "reconstruction"
        # Self-comparison validates geometry, coefficients and proper camera rotation.
        compare_fits(raw, raw, basis)
        neutral = neutral_vertices(raw, basis)
        stage = "landmarks"
        landmarks = project_vertices(raw, model.keypoint_coordinates)
        if landmarks.shape != (68, 3) or not np.isfinite(landmarks).all():
            raise ValueError("Invalid sparse projected landmarks.")
        record.update(
            topology_sha256=raw.topology_sha256,
            vertex_count=len(raw.vertices),
            shape=np.asarray(raw.shape).tolist(),
            expr=np.asarray(raw.expr).tolist(),
            projection=np.asarray(raw.projection).tolist(),
            roi=list(raw.roi),
            projected_landmarks=landmarks.tolist(),
            rotation=rotation.tolist(),
            projection_diagnostics=decomposition,
            projection_semantics="independent fit in this image's EXIF-corrected pixel frame",
            fitted_bbox_diagnostic={
                **source_frame(raw.vertices),
                "normalization_reference": "diagnostic_only_not_comparison_frame",
            },
        )
        if job["role"] == "original":
            record["canonical_frame"] = source_frame(raw.vertices)
        stage = "output"
        artifact = output / "fits" / (job["sample_id"] + ".npz")
        with artifact.open("xb") as stream:
            np.savez_compressed(
                stream,
                vertices=raw.vertices,
                neutral_vertices=neutral,
                shape=raw.shape,
                expr=raw.expr,
                projection=raw.projection,
                roi=np.asarray(raw.roi),
            )
        record.update(status="ok", fit_artifact=_pin(root, artifact))
        return record, raw
    except Exception as error:
        if stage == "output":
            raise
        code = (
            error.code
            if isinstance(error, ApiError)
            else {
                "hash": "HASH_MISMATCH",
                "input": "BAD_INPUT",
                "detection": "DETECTION_FAILED",
                "reconstruction": "MODEL_OR_TOPOLOGY_MISMATCH",
                "landmarks": "LANDMARK_INVALID",
                "pose": "POSE_OR_EXPRESSION_INVALID",
            }[stage]
        )
        record.update(error_code=code, failure_stage=stage, error_type=type(error).__name__)
        return record, None
    finally:
        record["seconds"] = perf_counter() - started


def _comparison(
    source_id: str,
    target_id: str,
    anchor_id: str,
    kind: str,
    fits: dict,
    records: dict,
    basis: np.ndarray,
    **metadata,
) -> dict:
    row = dict(
        subject_id=records[anchor_id]["subject_id"],
        source_id=source_id,
        target_id=target_id,
        reference_source_id=anchor_id,
        kind=kind,
        status="failed",
        **metadata,
    )
    missing = [name for name in (source_id, target_id, anchor_id) if name not in fits]
    if missing:
        row.update(
            error_code="FIT_UNAVAILABLE",
            fit_failures={name: records[name]["error_code"] for name in set(missing)},
        )
        return row
    frame = source_frame(fits[anchor_id].vertices)
    row["source_frame"] = frame
    try:
        row.update(compare_fits(fits[source_id], fits[target_id], basis, frame=frame), status="ok")
    except ValueError:
        row["error_code"] = "MODEL_OR_TOPOLOGY_MISMATCH"
    return row


def _comparisons(
    manifest: dict, study: str, jobs: list, fits: dict, records: dict, basis: np.ndarray
) -> list[dict]:
    result = []
    if study == "longitudinal":
        for pair in longitudinal_pairs(jobs):
            pair = dict(pair)
            source_id, target_id = pair.pop("source_id"), pair.pop("target_id")
            pair.pop("subject_id")
            result.append(
                _comparison(
                    source_id, target_id, source_id, "real_cross_age", fits, records, basis, **pair
                )
            )
        return result
    for case in manifest["bridge_cases"]:
        source_id = case["sample_id"]
        if case["source_status"] != "passed":
            continue
        aligned_id = source_id + "--aligned"
        result.append(
            _comparison(source_id, aligned_id, source_id, "source_vs_aligned", fits, records, basis)
        )
        control = case["same_age_control"]
        same_id = None
        if control["status"] in ("generated", "reused_existing"):
            same_id = f"{source_id}--sam-{control['target_age']:03d}"
            for baseline, kind in (
                (source_id, "source_vs_same_age"),
                (aligned_id, "aligned_vs_same_age"),
            ):
                result.append(
                    _comparison(
                        baseline,
                        same_id,
                        source_id,
                        kind,
                        fits,
                        records,
                        basis,
                        target_age=control["target_age"],
                    )
                )
        for target in case["target_runs"]:
            age = target["target_age"]
            target_id = f"{source_id}--sam-{age:03d}"
            result.append(
                _comparison(
                    source_id,
                    target_id,
                    source_id,
                    "source_vs_target",
                    fits,
                    records,
                    basis,
                    target_age=age,
                )
            )
            if same_id is not None and target_id != same_id:
                result.append(
                    _comparison(
                        same_id,
                        target_id,
                        source_id,
                        "same_age_vs_target",
                        fits,
                        records,
                        basis,
                        target_age=age,
                    )
                )
    return result


def run_study(args, manifest: dict, output: Path, report: dict) -> None:
    owned = {}
    fits, records = {}, {}
    try:
        jobs = _jobs(manifest, args.study)
        basis = _load_models(args, manifest, report, owned)
        topology_path = output / "topology.npz"
        with topology_path.open("xb") as stream:
            np.savez_compressed(
                stream,
                triangles=owned["reconstructor"].triangles,
                keypoint_coordinates=owned["reconstructor"].keypoint_coordinates,
            )
        report["topology_artifact"] = _pin(args.root, topology_path)
        (output / "fits").mkdir()
        for job in jobs:
            record, raw = _fit_one(args.root, job, owned, basis, output)
            records[job["sample_id"]] = record
            if raw is not None:
                fits[job["sample_id"]] = raw
        for record in records.values():
            anchor = record.get("reference_source_id", record["sample_id"])
            record["source_canonical_frame"] = (
                source_frame(fits[anchor].vertices) if anchor in fits else None
            )
        report["fit_records"] = list(records.values())
        comparisons = _comparisons(manifest, args.study, jobs, fits, records, basis)
        report["comparison_records"] = comparisons
        fit_rows = [
            dict(
                record,
                input_path=record["input"]["path"],
                input_sha256=record["input"]["sha256"],
                fit_path=record.get("fit_artifact", {}).get("path"),
            )
            for record in records.values()
        ]
        _write_csv(
            output / "fits.csv",
            fit_rows,
            [
                "sample_id",
                "subject_id",
                "role",
                "source_age",
                "target_age",
                "status",
                "error_code",
                "failure_stage",
                "face_count",
                "vertex_count",
                "seconds",
                "input_path",
                "input_sha256",
                "fit_path",
            ],
        )
        _write_csv(
            output / "comparisons.csv",
            comparisons,
            [
                "kind",
                "subject_id",
                "source_id",
                "target_id",
                "reference_source_id",
                "source_age",
                "target_age",
                "status",
                "error_code",
                *_METRICS,
            ],
        )
        report["tabular_artifacts"] = {
            name: _pin(args.root, output / name) for name in ("fits.csv", "comparisons.csv")
        }
        kinds = sorted({row["kind"] for row in comparisons})
        report["summary"] = {
            "requested_images": len(jobs),
            "fit_statuses": dict(Counter(row["status"] for row in records.values())),
            "failures": dict(
                Counter(row["error_code"] for row in records.values() if row["status"] != "ok")
            ),
            "images_by_role": dict(Counter(row["role"] for row in jobs)),
            "comparisons": {
                kind: aggregate_identity_metrics(
                    [row for row in comparisons if row["kind"] == kind], _METRICS
                )
                for kind in kinds
            },
        }
        report["technical_execution"] = "passed"
    finally:
        for model in owned.values():
            _dispose(model)
        owned.clear()
        fits.clear()
        report["model_ownership_released"] = True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, choices=("longitudinal", "generated"))
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument(
        "--protocol-manifest",
        default="output/research/age-protocol-20261020/verified/manifest.json",
    )
    parser.add_argument(
        "--frozen-inputs", default="output/research/age-protocol-20261020/freeze.json"
    )
    parser.add_argument("--detector-manifest", default="data/models/yolov5n05-face/manifest.json")
    parser.add_argument("--reconstructor-manifest", default="data/models/3ddfa-v2/manifest.json")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--research-allow-unresolved", action="store_true")
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    report = {
        "schema_version": 1,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "study": args.study,
        "scope": "development-only N1/N2 geometric proxy research",
        "research_only": True,
        "service_ready": False,
        "g3_complete": False,
        "years_calibrated": False,
        "identity_accepted": False,
        "uv_registered": False,
        "training_use": False,
        "independent_external_evaluation": False,
        "technical_execution": "failed",
        "models": {},
        "units": "source canonical display units, not metric or calibrated years",
        "quality_thresholds_established": False,
    }
    output = None
    created = False
    try:
        output = _path(args.root, args.output_dir)
        if output.exists():
            raise FileExistsError("Output directory already exists; prior evidence is preserved.")
        manifest_path = _path(args.root, args.protocol_manifest)
        freeze_path = _path(args.root, args.frozen_inputs)
        manifest = _verified_protocol(args.root, manifest_path, freeze_path)
        report["protocol_id"] = manifest["protocol_id"]
        report["inputs"] = {
            "protocol_manifest": _pin(args.root, manifest_path),
            "pre_inference_freeze": _pin(args.root, freeze_path),
        }
        args.detector_manifest = _path(args.root, args.detector_manifest)
        args.reconstructor_manifest = _path(args.root, args.reconstructor_manifest)
        output.mkdir(parents=True, exist_ok=False)
        created = True
        run_study(args, manifest, output, report)
        _write_json(output / "report.json", report)
        _write_json(output / "summary.json", report["summary"])
        print(
            json.dumps(
                {
                    "study": args.study,
                    "technical_execution": "passed",
                    "requested_images": report["summary"]["requested_images"],
                    "fit_statuses": report["summary"]["fit_statuses"],
                }
            )
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        report.update(
            error_code="MODEL_ASSET_ERROR"
            if isinstance(error, ModelAssetError)
            else "STUDY_FAILED",
            error_type=type(error).__name__,
        )
        if created and output is not None and not (output / "report.json").exists():
            _write_json(output / "report.json", report)
        print(
            json.dumps(
                {
                    "technical_execution": "failed",
                    "error_code": report["error_code"],
                    "error_type": type(error).__name__,
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

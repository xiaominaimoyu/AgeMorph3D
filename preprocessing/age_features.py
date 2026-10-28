"""Build raw shape40 research data from hash-bound original-photo fit JSON.

Run from the workspace: python -m preprocessing.age_features --help
No images, NPZ files, weights, models or research-holdout results are opened.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path, PurePosixPath

MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 5000
GROUP = "calibration_research"
PROJECTION = "independent fit in this image's EXIF-corrected pixel frame"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def research_age_label(kind: str, value=None, *, lower=None, upper=None) -> dict:
    """Keep exact, interval and unknown labels distinct; never impute an age."""
    if kind == "exact":
        _require(_number(value) and 20 <= value <= 70, "Invalid exact adult age label.")
        _require(lower is None and upper is None, "Exact age cannot carry interval bounds.")
    elif kind == "interval":
        _require(value is None, "An interval must not carry an exact/midpoint age.")
        _require(
            _number(lower) and _number(upper) and 20 <= lower < upper <= 70,
            "Invalid adult age interval.",
        )
    else:
        _require(kind == "unknown", "Unsupported research age kind.")
        _require(value is lower is upper is None, "Unknown age must remain null.")
    return {"kind": kind, "value": value, "lower": lower, "upper": upper}


def _pin(value: dict) -> dict:
    _require(isinstance(value, dict), "Expected a file declaration.")
    path = value.get("path")
    _require(isinstance(path, str) and bool(path), "Invalid declared path.")
    normalized = PurePosixPath(path)
    _require(
        "\\" not in path
        and ":" not in path
        and not normalized.is_absolute()
        and ".." not in normalized.parts
        and normalized.as_posix() == path,
        "Declared paths must be normalized workspace-relative paths.",
    )
    _require(
        isinstance(value.get("sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is not None,
        "Invalid declared SHA-256.",
    )
    _require(type(value.get("bytes")) is int and value["bytes"] > 0, "Invalid file size.")
    return {key: value[key] for key in ("path", "sha256", "bytes")}


def _vector(value: object, size: int) -> bool:
    return isinstance(value, list) and len(value) == size and all(map(_number, value))


def _closed(document: dict, fields: tuple[str, ...]) -> None:
    _require(document.get("research_only") is True, "Input must be research-only.")
    _require(all(document.get(k) is False for k in fields), "Input eligibility is not closed.")


def build_feature_dataset(
    report: dict, manifest: dict, freeze: dict, protocol: dict, dataset: dict, models: dict
) -> dict:
    """Validate supplied metadata and return detached, deterministic research data.

    File integrity is enforced by ``export_dataset``. Binary pins below remain
    declarations from the old report, never a new verification of those assets.
    """
    _closed(
        report,
        (
            "training_use",
            "service_ready",
            "g3_complete",
            "independent_external_evaluation",
            "years_calibrated",
        ),
    )
    _closed(
        manifest,
        ("training_use", "service_ready", "g3_complete", "independent_external_evaluation"),
    )
    _require(
        report.get("schema_version") == manifest.get("schema_version") == 1,
        "Unsupported input schema.",
    )
    _require(
        report.get("study") == "calibration" and report.get("technical_execution") == "passed",
        "Only completed calibration-original studies are supported.",
    )
    _require(
        report.get("protocol_id")
        == manifest.get("protocol_id")
        == freeze.get("protocol_id")
        == protocol.get("protocol_id"),
        "Protocol identifiers differ.",
    )
    _require(
        protocol.get("source_age_policy") == "unknown_stays_null"
        and freeze.get("before_new_control_inference") is True,
        "Unsupported source-age or freeze policy.",
    )
    _require(
        report.get("units") == "source canonical display units, not metric or calibrated years",
        "Unknown study coordinate convention.",
    )

    identities = manifest["identities"]
    images = manifest["adult_images"]
    _require(
        isinstance(identities, list)
        and isinstance(images, list)
        and 0 < len(images) <= MAX_RECORDS
        and 0 < len(identities) <= MAX_RECORDS,
        "Invalid research inventory size.",
    )
    groups = {r["subject_id"]: r["group"] for r in identities}
    _require(
        len(groups) == len(identities) and groups == freeze["identity_groups"],
        "Identity groups differ from the pre-inference freeze.",
    )
    grouping = protocol["grouping"]
    development = set(grouping["development_subject_ids"])
    _require(development <= groups.keys(), "Development identities missing.")
    ordered = sorted(
        set(groups) - development,
        key=lambda s: hashlib.sha256(f"{grouping['seed']}:{s}".encode()).hexdigest(),
    )
    count = grouping["calibration_identity_count"]
    _require(type(count) is int and 0 <= count <= len(ordered), "Invalid calibration count.")
    calibration = set(ordered[:count])
    expected_groups = {
        s: "development"
        if s in development
        else GROUP
        if s in calibration
        else "evaluation_research_holdout"
        for s in groups
    }
    _require(groups == expected_groups, "Identity purposes violate the frozen protocol.")
    _require(
        len(images) == protocol["expected_adult_images"]
        and len(groups) == protocol["expected_adult_identities"],
        "Inventory count mismatch.",
    )
    identity_rows = {r["subject_id"]: r for r in identities}
    expected, seen_paths, digest_groups, used_subjects = {}, set(), {}, set()
    for image in images:
        pin = _pin(image)
        subject = image["subject_id"]
        _require(subject in groups and image["group"] == groups[subject], "Cross-group image.")
        _require(pin["path"] not in seen_paths, "Duplicate original image path.")
        seen_paths.add(pin["path"])
        used_subjects.add(subject)
        _require(
            digest_groups.setdefault(pin["sha256"], image["group"]) == image["group"],
            "Identical image bytes declared across identity-use groups.",
        )
        if image["group"] != GROUP:
            continue
        filename = PurePosixPath(pin["path"]).name
        match = re.fullmatch(r"(\d{3})A(\d{2})[A-Za-z]?\.JPG", filename, re.I)
        age = image["source_age"]
        _require(
            match is not None
            and subject == match[1]
            and type(age) is int
            and age == int(match[2])
            and 20 <= age <= 70,
            "Invalid FGNET label.",
        )
        sample_id = "fgnet-" + PurePosixPath(filename).stem.lower()
        _require(sample_id not in expected, "Duplicate sample identifier.")
        expected[sample_id] = image
    _require(used_subjects == set(groups), "Inventory omits an identity.")

    declared_models = {}
    for role, backend, roles in (
        ("detector", "yolov5_face_onnx", {"detector"}),
        ("reconstructor", "3ddfa_v2_onnx", {"regressor", "bfm", "param_stats"}),
    ):
        old, model = report["models"][role], models[role]
        manifest_pin = _pin(old["manifest"])
        _require(
            old["manifest_sha256"] == manifest_pin["sha256"]
            and old["model_id"] == model["model_id"]
            and old["backend"] == model["backend"] == backend,
            "Model binding mismatch.",
        )
        artifacts = {}
        for item in model["artifacts"]:
            name = item["role"]
            _require(name not in artifacts, "Duplicate model artifact role.")
            path = (PurePosixPath(manifest_pin["path"]).parent / item["path"]).as_posix()
            artifacts[name] = _pin(
                {"path": path, "sha256": item["sha256"], "bytes": item["size_bytes"]}
            )
        _require(set(artifacts) == roles, "Unexpected model artifact roles.")
        previous = [_pin(p) for p in old["artifacts"]]
        _require(
            len(previous) == len(artifacts)
            and sorted(previous, key=str) == sorted(artifacts.values(), key=str),
            "Model/basis artifact declarations differ.",
        )
        declared_models[role] = {
            "model_id": model["model_id"],
            "backend": backend,
            "manifest": manifest_pin,
            "artifacts": artifacts,
            "license_status": model["license_status"],
        }
    basis = report["expression_basis"]
    _require(
        _pin(basis["asset"]) == declared_models["reconstructor"]["artifacts"]["bfm"],
        "Expression and shape basis bindings differ.",
    )
    dims = basis["shape"]
    _require(
        isinstance(dims, list)
        and len(dims) == 2
        and type(dims[0]) is int
        and 0 < dims[0] <= 4_500_000
        and dims[0] % 3 == 0
        and dims[1] == 10,
        "Invalid expression basis dimensions.",
    )
    fits = report["fit_records"]
    _require(isinstance(fits, list) and 0 < len(fits) <= MAX_RECORDS, "Invalid fit request count.")
    by_id = {r["sample_id"]: r for r in fits}
    _require(
        len(by_id) == len(fits) and set(by_id) == set(expected),
        "Fit requests must exactly cover frozen calibration originals.",
    )
    records, shape, expression, projections, indices = [], [], [], [], []
    topology = None
    for sample_id in sorted(expected):
        image, row = expected[sample_id], by_id[sample_id]
        _require(
            row["role"] == "original"
            and row["data_group"] == GROUP
            and row["subject_id"] == image["subject_id"]
            and type(row["source_age"]) is int
            and row["source_age"] == image["source_age"]
            and _pin(row["input"]) == _pin(image)
            and not any(k in row for k in ("target_age", "reference_source_id")),
            "Fit is not the requested original photograph.",
        )
        identity = identity_rows[image["subject_id"]]
        _require(
            identity.get("historical_preprocessing_exposed") is True
            and type(identity.get("previously_viewed")) is bool,
            "Missing historical exposure declaration.",
        )
        record = {
            "sample_id": sample_id,
            "subject_id": image["subject_id"],
            "group": GROUP,
            "original_image": _pin(image),
            "research_age": {
                **research_age_label("exact", image["source_age"]),
                "provenance": "dataset_filename",
                "independently_verified": False,
            },
            "exposure_history": {
                "historical_preprocessing_exposed": True,
                "n0_previously_viewed": identity["previously_viewed"],
                "subsequent_research_calibration_exposed": True,
            },
            "fit_status": row["status"],
            "error_code": row["error_code"],
            "feature_row_index": None,
        }
        _require(row["status"] in ("ok", "failed"), "Unknown fit status.")
        if row["status"] == "failed":
            _require(
                isinstance(row["error_code"], str) and bool(row["error_code"]),
                "Failed requests need an error code.",
            )
            record["failure_stage"] = row.get("failure_stage")
        else:
            _require(
                row["error_code"] is None
                and _vector(row["shape"], 40)
                and _vector(row["expr"], 10)
                and isinstance(row["projection"], list)
                and len(row["projection"]) == 3
                and all(_vector(v, 4) for v in row["projection"]),
                "Invalid fit coefficients.",
            )
            roi, frame = row["roi"], row["canonical_frame"]
            _require(
                _vector(roi, 4)
                and roi[0] < roi[2]
                and roi[1] < roi[3]
                and _vector(frame["source_center"], 3)
                and _number(frame["source_to_canonical_uniform_scale"])
                and frame["source_to_canonical_uniform_scale"] > 0
                and frame["normalization_reference"] == "unchanged_source_mesh"
                and frame == row["source_canonical_frame"]
                and row["projection_semantics"] == PROJECTION,
                "Coordinate convention mismatch.",
            )
            digest = row["topology_sha256"]
            _require(
                isinstance(digest, str)
                and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
                and (topology is None or digest == topology)
                and type(row["vertex_count"]) is int
                and row["vertex_count"] == dims[0] // 3,
                "Inconsistent topology/vertex order declaration.",
            )
            topology = digest
            record.update(
                feature_row_index=len(shape),
                fit_artifact=_pin(row["fit_artifact"]),
                roi=roi,
                source_canonical_frame=frame,
            )
            indices.append(len(records))
            shape.append(row["shape"])
            expression.append(row["expr"])
            projections.append(row["projection"])
        records.append(record)
    summary = {
        "requested": len(records),
        "valid": len(shape),
        "failed": len(records) - len(shape),
        "identities": len(calibration),
        "failure_codes": dict(
            sorted(Counter(r["error_code"] for r in records if r["fit_status"] == "failed").items())
        ),
    }
    _require(
        report["summary"]["requested_images"] == summary["requested"]
        and report["summary"]["fit_statuses"] == dict(Counter(r["fit_status"] for r in records)),
        "Saved summary differs from the full request denominator.",
    )
    result = {
        "schema_version": 1,
        "dataset_type": "original_photo_raw_shape40_research",
        "research_only": True,
        "training_use": False,
        "production_eligible": False,
        "service_ready": False,
        "g3_complete": False,
        "years_calibrated": False,
        "independent_external_evaluation": False,
        "binding": {
            "protocol_id": report["protocol_id"],
            "models": declared_models,
            "topology_artifact": _pin(report["topology_artifact"]),
            "topology_sha256": topology,
            "vertex_count": dims[0] // 3,
            "shape_space": "3ddfa_raw_shape_coefficients_first_40",
            "shape_dimensions": 40,
            "expression_dimensions": 10,
            "standardized": False,
            "identity_centered": False,
            "projection_is_learning_feature": False,
            "binary_verification": "historical_declarations_unread",
            "geometry_ground_truth": False,
        },
        "dataset_provenance": dataset,
        "records": records,
        "features": {
            "record_indices": indices,
            "shape": shape,
            "expression": expression,
            "projection": projections,
        },
        "summary": summary,
    }
    return copy.deepcopy(result)


def _workspace_path(root: Path, value: str) -> Path:
    path = root.joinpath(_pin({"path": value, "sha256": "0" * 64, "bytes": 1})["path"]).resolve()
    _require(root in path.parents, "Path escapes the workspace.")
    return path


class _JsonInputs:
    def __init__(self, root: Path):
        self.root = root
        self.pins: dict[str, dict] = {}

    def read(self, pin: dict) -> dict:
        pin = _pin(pin)
        path = _workspace_path(self.root, pin["path"])
        _require(
            path.suffix == ".json" and pin["bytes"] <= MAX_JSON_BYTES,
            "Only bounded JSON metadata inputs may be read.",
        )
        with path.open("rb") as stream:
            payload = stream.read(MAX_JSON_BYTES + 1)
        _require(
            len(payload) == pin["bytes"] and hashlib.sha256(payload).hexdigest() == pin["sha256"],
            f"Metadata fingerprint mismatch: {pin['path']}",
        )
        old = self.pins.setdefault(pin["path"], pin)
        _require(old == pin, "Conflicting input fingerprints.")

        def unique(pairs):
            result = {}
            for key, value in pairs:
                _require(key not in result, "Duplicate JSON key.")
                result[key] = value
            return result

        obj = json.loads(payload, object_pairs_hook=unique)
        _require(isinstance(obj, dict), "Expected a JSON object.")
        return obj

    def recheck(self) -> None:
        for pin in list(self.pins.values()):
            self.read(pin)


def export_dataset(root: Path, report_path: str, report_sha256: str, output_dir: str) -> dict:
    """Read the exact JSON closure, then write dataset.json in a fresh ignored directory."""
    root = root.resolve()
    output = _workspace_path(root, output_dir)
    _require(
        PurePosixPath(output_dir).parts[0] in ("output", "data")
        and len(PurePosixPath(output_dir).parts) > 1,
        "Output must be under output/ or data/.",
    )
    _require(
        any(root / name in output.parents for name in ("output", "data")),
        "Resolved output must remain in output/ or data/.",
    )
    _require(not output.exists(), "Output directory already exists; refusing to overwrite.")
    path = _workspace_path(root, report_path)
    inputs = _JsonInputs(root)
    report = inputs.read(
        {"path": report_path, "sha256": report_sha256, "bytes": path.stat().st_size}
    )
    manifest_pin = report["inputs"]["protocol_manifest"]
    manifest = inputs.read(manifest_pin)
    freeze_pin = report["inputs"]["pre_inference_freeze"]
    _require(
        _pin(freeze_pin) == _pin(manifest["inputs"]["pre_inference_freeze"]),
        "Pre-inference freeze binding differs.",
    )
    freeze = inputs.read(freeze_pin)
    for name, pin in manifest["inputs"].items():
        _pin(pin)
        if name != "pre_inference_freeze":
            _require(freeze["inputs"].get(pin["path"]) == pin["sha256"], "N0 freeze pin mismatch.")
    protocol = inputs.read(manifest["inputs"]["protocol"])
    dataset = inputs.read(manifest["inputs"]["dataset_manifest"])
    models = {
        role: inputs.read(report["models"][role]["manifest"])
        for role in ("detector", "reconstructor")
    }
    result = build_feature_dataset(report, manifest, freeze, protocol, dataset, models)
    result["verified_json_inputs"] = sorted(inputs.pins.values(), key=lambda p: p["path"])
    payload = (json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode(
        "utf-8"
    )
    inputs.recheck()
    output.mkdir(parents=True, exist_ok=False)
    destination = output / "dataset.json"
    try:
        with destination.open("xb") as stream:
            stream.write(payload)
        inputs.recheck()
    except BaseException:
        destination.unlink(missing_ok=True)
        output.rmdir()
        raise
    return {
        "path": destination.relative_to(root).as_posix(),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "summary": result["summary"],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--report", required=True, help="Workspace-relative original-fit JSON report"
    )
    parser.add_argument("--report-sha256", required=True)
    parser.add_argument(
        "--output-dir", required=True, help="Fresh directory within output/ or data/"
    )
    args = parser.parse_args(argv)
    try:
        result = export_dataset(args.root, args.report, args.report_sha256, args.output_dir)
    except (ValueError, OSError, KeyError, TypeError, RecursionError) as error:
        print(f"Age feature export refused: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

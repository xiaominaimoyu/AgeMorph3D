"""Fit one retrospective age-score bias offset without reading images or models."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ID = "agemorph3d-age-calibration-v1"
AGE_ID = "agemorph3d-age-evaluator-v1"
GROUPS = ("development", "calibration_research")
STRATA = ("all", "20-29", "30-39", "40-49", "50-59", "60-69", "70")
ROLES = (
    "protocol",
    "age_protocol",
    "age_study_plan",
    "age_verification",
    "age_report",
    "n0_manifest",
)
SOURCES = (
    "tools/age_calibration_probe.py",
    "backend/tests/test_age_calibration_probe.py",
    "tools/identity_calibration_probe.py",
)
FLAGS = {
    "research_only": True,
    **dict.fromkeys(
        (
            "new_model_inference",
            "holdout_age_predictions_extracted",
            "calibration_group_refitted",
            "years_calibrated",
            "age_quality_accepted",
            "identity_quality_accepted",
            "independent_evaluation",
            "training_overlap_excluded",
            "legal_permission_established",
            "service_ready",
            "production_enabled",
            "g3_complete",
        ),
        False,
    ),
}
OLD_FLAGS = {
    key: FLAGS[key]
    for key in (
        "research_only",
        "age_quality_accepted",
        "years_calibrated",
        "independent_evaluation",
        "training_overlap_excluded",
        "legal_permission_established",
        "service_ready",
        "production_enabled",
        "g3_complete",
    )
}
METRICS = (
    "raw_mae",
    "raw_bias",
    "raw_rmse",
    "corrected_mae",
    "corrected_bias",
    "corrected_rmse",
    "mae_reduction",
    "rmse_reduction",
)
LIMIT = 2 * 1024**2
MAX_RECORDS = 500
MAX_ABS_PREDICTION = 1e6
REPLICATES = 1000
SEED = 20261027


def _source_hash(path):
    with Path(path).open("rb") as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("Implementation source exceeds its byte bound.")
    return hashlib.sha256(data).hexdigest()


LOADED_CODE_SHA256 = _source_hash(__file__)
_helper_spec = importlib.util.spec_from_file_location(
    "_age_calibration_integrity", ROOT / SOURCES[2]
)
integrity = importlib.util.module_from_spec(_helper_spec)
_helper_spec.loader.exec_module(integrity)
runtime_fingerprint = integrity.runtime_fingerprint


def _json(data):
    value = integrity._json(data)
    pending = [(value, 0)]
    visited = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        if depth > 64 or visited > 100_000:
            raise ValueError("Metadata structure exceeds its bound.")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Nonfinite metadata number.")
    return value


def _number(value, maximum=MAX_ABS_PREDICTION):
    if type(value) not in (int, float) or abs(value) > maximum or not math.isfinite(value):
        raise ValueError("Invalid bounded age prediction.")
    return float(value)


def _label(value):
    return integrity._integer(value, 20, 70)


def _image_pin(value):
    """Validate image metadata only; never open the referenced image."""
    if not isinstance(value, dict):
        raise ValueError("Missing original image metadata.")
    # The metadata-file helper has a 2 MiB file bound, unlike a pinned photograph.
    size = integrity._integer(value.get("bytes"), 0, 10 * 1024**2)
    result = integrity._pin({**value, "bytes": 0})
    return {**result, "bytes": size}


def _closed(value, expected):
    if not isinstance(value, dict) or any(
        value.get(key) is not flag for key, flag in expected.items()
    ):
        raise ValueError("Research qualification flags differ.")
    for key, flag in value.items():
        if (
            key.endswith("_accepted")
            or key in {"service_ready", "production_enabled", "g3_complete", "years_calibrated"}
        ) and flag is not False:
            raise ValueError("Research metadata cannot grant qualification.")


def _contains(values, pin):
    return integrity._contains_pin(values, pin)


def validate_protocol(protocol):
    if (
        protocol.get("schema_version") != 1
        or protocol.get("protocol_id") != PROTOCOL_ID
        or protocol.get("roles") != list(ROLES)
        or protocol.get("quality_threshold", 1) is not None
        or protocol.get("selection", {}).get("policy_id")
        != "development-subject-macro-additive-offset-v1"
        or protocol.get("selection", {}).get("fit_group") != "development"
        or protocol.get("evaluation", {}).get("groups") != list(GROUPS)
        or protocol.get("evaluation", {}).get("age_strata") != list(STRATA)
        or protocol.get("uncertainty", {}).get("policy_id")
        != "fixed-offset-subject-paired-randrange-v1"
        or protocol.get("uncertainty", {}).get("replicates") != REPLICATES
        or protocol.get("uncertainty", {}).get("seed") != SEED
    ):
        raise ValueError("Unsupported frozen calibration policy.")
    _closed(protocol.get("flags"), FLAGS)


def parse_records(metadata, roles):
    """Bind saved original scores to N0; inspect no image or old metadata descendants."""
    protocol, old, plan, verification, report, n0 = (metadata[key] for key in ROLES)
    validate_protocol(protocol)
    if old.get("protocol_id") != AGE_ID or old.get("quality_threshold", 1) is not None:
        raise ValueError("Unsupported historical age protocol.")
    _closed(old.get("flags"), OLD_FLAGS)
    if (
        plan.get("protocol_id") != AGE_ID
        or plan.get("protocol") != roles["age_protocol"]
        or plan.get("n0_manifest") != roles["n0_manifest"]
        or not _contains(verification.get("evidence"), roles["age_study_plan"])
        or not _contains(verification.get("evidence"), roles["age_report"])
    ):
        raise ValueError("Historical verification/plan bindings differ.")
    _closed(report, OLD_FLAGS)
    if (
        report.get("protocol_id") != AGE_ID
        or report.get("integrity_status") != "passed"
        or report.get("quality_threshold", 1) is not None
        or report.get("models_closed") is not True
        or report.get("holdout_age_predictions_extracted") is not False
        or report.get("images_or_crops_written") is not False
        or report.get("execution_status") not in {"complete", "completed_with_failures"}
        or any(
            not _contains(report.get("inputs"), roles[key])
            for key in ("age_study_plan", "age_protocol", "n0_manifest")
        )
    ):
        raise ValueError("Historical age report is not bound, closed research evidence.")
    if (
        n0.get("protocol_id") != "agemorph3d-age-research-v1"
        or n0.get("research_only") is not True
        or any(n0.get(key) is not False for key in ("training_use", "service_ready", "g3_complete"))
    ):
        raise ValueError("N0 research boundary differs.")
    identities = {}
    for item in integrity._list(n0.get("identities")):
        subject = integrity._subject(item.get("subject_id"))
        group = item.get("group")
        if subject in identities or group not in {*GROUPS, "evaluation_research_holdout"}:
            raise ValueError("Duplicate identity or cross-group identity leakage.")
        identities[subject] = group
    expected, source_groups, held_out = {}, {}, 0
    for item in integrity._list(n0.get("adult_images")):
        source = _image_pin(item)
        subject = integrity._subject(item.get("subject_id"))
        group = item.get("group")
        label = _label(item.get("source_age"))
        if identities.get(subject) != group or source["path"] in expected:
            raise ValueError("N0 image identity/group or unique path differs.")
        digest_group = source_groups.setdefault(source["sha256"], group)
        if digest_group != group:
            raise ValueError("Identical image hash leaks across identity groups.")
        expected[source["path"]] = {
            "source": source,
            "subject_id": subject,
            "group": group,
            "source_age_label": label,
        }
        held_out += group == "evaluation_research_holdout"
    held_out_paths = {
        path for path, item in expected.items() if item["group"] == "evaluation_research_holdout"
    }
    held_out_hashes = {expected[path]["source"]["sha256"] for path in held_out_paths}
    rows, excluded, seen_ids, seen_paths, original_paths = [], Counter(), set(), set(), set()
    records = integrity._list(report.get("records"))
    successful = failures = sources = generated = 0
    for record in records:
        image_id = integrity._integer(record.get("image_id"), 0, MAX_RECORDS)
        source = _image_pin(record.get("source"))
        group = record.get("group")
        if source["path"] in held_out_paths or source["sha256"] in held_out_hashes:
            raise ValueError("Held-out image prediction cannot be disguised as an excluded role.")
        if image_id in seen_ids or source["path"] in seen_paths or group not in GROUPS:
            raise ValueError("Duplicate score record or held-out prediction.")
        seen_ids.add(image_id)
        seen_paths.add(source["path"])
        record_roles = record.get("roles")
        if (
            not isinstance(record_roles, list)
            or not record_roles
            or len(record_roles) != len(set(record_roles))
            or set(record_roles)
            not in ({"original"}, {"original", "source"}, {"source"}, {"generated"})
        ):
            raise ValueError("Unsupported historical image roles.")
        sources += "source" in record_roles
        generated += "generated" in record_roles
        status = integrity._text(record.get("status"), 100)
        estimate, raw_estimate = record.get("age_estimate"), record.get("raw_age_estimate")
        if status == "ok":
            estimate, raw_estimate = _number(estimate), _number(raw_estimate)
            if not math.isclose(estimate, raw_estimate * 122 + 61, rel_tol=1e-6, abs_tol=1e-5):
                raise ValueError("Saved MiVOLO age conversion differs.")
            successful += 1
        else:
            if estimate is not None or raw_estimate is not None:
                raise ValueError("Failed prediction must remain null.")
            failures += 1
        if "original" not in record_roles:
            if source["path"] in expected:
                raise ValueError("Original N0 image was relabelled as an excluded record.")
            excluded["generated" if "generated" in record_roles else "source_only"] += 1
            continue
        item = expected.get(source["path"])
        if item is None or item["group"] not in GROUPS:
            raise ValueError("Original score is absent from allowed N0 originals.")
        if any(record.get(key) != value for key, value in item.items()):
            raise ValueError("Original source, label or identity/group binding differs.")
        if record.get("source_changed") is not False:
            raise ValueError("Changed original image evidence is prohibited.")
        for phase in ("initial_source_check", "final_source_check"):
            if record.get(phase) != {
                **source,
                "verification": "verified",
                "matches_declared": True,
            }:
                raise ValueError("Original source integrity evidence differs.")
        original_paths.add(source["path"])
        rows.append(
            {
                "image_id": image_id,
                **item,
                "roles": record_roles,
                "status": status,
                "age_estimate": estimate,
            }
        )
    expected_paths = {path for path, item in expected.items() if item["group"] in GROUPS}
    cohort = old.get("cohort", {})
    if (
        seen_ids != set(range(len(records)))
        or original_paths != expected_paths
        or cohort.get("groups") != list(GROUPS)
        or cohort.get("expected_originals") != len(rows)
        or cohort.get("expected_generated") != generated
        or cohort.get("expected_sources") != sources
        or cohort.get("expected_unique_images") != len(records)
        or cohort.get("expected_reused_detection_failures") != failures
        or report.get("image_counts")
        != {"requested": len(records), "successful": successful, "failed": failures}
    ):
        raise ValueError("Historical or N0 requested/failed cohort denominator differs.")
    accounting = {
        "all_saved_records": len(records),
        "original_requested": len(rows),
        "original_scored": sum(row["age_estimate"] is not None for row in rows),
        "original_failed": sum(row["age_estimate"] is None for row in rows),
        "excluded_generated": excluded["generated"],
        "excluded_source_only": excluded["source_only"],
        "held_out_metadata_excluded": held_out,
        "original_group_counts": dict(Counter(row["group"] for row in rows)),
        "original_failure_statuses": dict(
            Counter(row["status"] for row in rows if row["age_estimate"] is None)
        ),
    }
    return rows, accounting


def _units(rows, offset):
    offset = _number(offset, MAX_ABS_PREDICTION + 70)
    buckets = defaultdict(list)
    for row in rows:
        buckets[integrity._subject(row["subject_id"])].append(row)
    units = []
    for subject, observations in sorted(buckets.items()):
        errors, corrected = [], []
        for row in observations:
            label = _label(row["source_age_label"])
            estimate = row["age_estimate"]
            if estimate is not None:
                estimate = _number(estimate)
                errors.append(estimate - label)
                corrected.append((estimate + offset) - label)
        count, scored = len(observations), len(errors)
        unit = {
            "subject_id": subject,
            "requested": count,
            "scored": scored,
            "failed": count - scored,
        }
        for prefix, values in (("raw", errors), ("corrected", corrected)):
            unit[prefix + "_mae"] = math.fsum(map(abs, values)) / scored if scored else None
            unit[prefix + "_bias"] = math.fsum(values) / scored if scored else None
            unit[prefix + "_mse"] = (
                math.fsum(value * value for value in values) / scored if scored else None
            )
            unit[prefix + "_requested_mae_lower"] = math.fsum(map(abs, values)) / count
        units.append(unit)
    return units


def fit_offset(rows):
    development = [
        row
        for row in rows
        if row["group"] == "development" and "original" in row.get("roles", ["original"])
    ]
    units = _units(development, 0)
    effective = [unit for unit in units if unit["scored"]]
    if not effective:
        raise ValueError("No scored development subject; an age offset cannot be fitted.")
    return {
        "offset_years": -math.fsum(unit["raw_bias"] for unit in effective) / len(effective),
        "development_unit_biases": [
            {"subject_id": unit["subject_id"], "scored": unit["scored"], "bias": unit["raw_bias"]}
            for unit in effective
        ],
        "requested": sum(unit["requested"] for unit in units),
        "scored": sum(unit["scored"] for unit in units),
        "failed": sum(unit["failed"] for unit in units),
        "eligible_units": len(units),
        "effective_units": len(effective),
        "fit_group": "development",
        "development_in_sample": True,
    }


def _metrics(units):
    if not units:
        return dict.fromkeys(METRICS)
    result = {}
    for prefix in ("raw", "corrected"):
        result[prefix + "_mae"] = math.fsum(unit[prefix + "_mae"] for unit in units) / len(units)
        result[prefix + "_bias"] = math.fsum(unit[prefix + "_bias"] for unit in units) / len(units)
        result[prefix + "_rmse"] = math.sqrt(
            math.fsum(unit[prefix + "_mse"] for unit in units) / len(units)
        )
    result["mae_reduction"] = result["raw_mae"] - result["corrected_mae"]
    result["rmse_reduction"] = result["raw_rmse"] - result["corrected_rmse"]
    return result


def percentile(values, probability):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def bootstrap(units, key):
    effective = [unit for unit in units if unit["scored"]]
    seed = SEED + int(hashlib.sha256(key.encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    repeats = {metric: [] for metric in METRICS}
    if effective:
        for _ in range(REPLICATES):
            sample = [effective[rng.randrange(len(effective))] for _ in effective]
            for metric, value in _metrics(sample).items():
                repeats[metric].append(value)
    return {
        "key": key,
        "seed": seed,
        "replicates": REPLICATES,
        "unit_order": [unit["subject_id"] for unit in effective],
        "metrics": {
            metric: {
                "low": percentile(values, 0.025),
                "high": percentile(values, 0.975),
                "valid_replicates": len(values),
                "sha256": hashlib.sha256(
                    json.dumps(values, separators=(",", ":"), allow_nan=False).encode()
                ).hexdigest(),
            }
            for metric, values in repeats.items()
        },
    }


def summary(rows, offset, key):
    units = _units(rows, offset)
    metrics = _metrics([unit for unit in units if unit["scored"]])
    failed = sum(unit["failed"] for unit in units)
    bounds = {}
    for prefix in ("raw", "corrected"):
        lower = (
            (math.fsum(unit[prefix + "_requested_mae_lower"] for unit in units) / len(units))
            if units
            else None
        )
        bounds[prefix] = {"lower": lower, "upper": None if failed else lower}
    return {
        "requested": sum(unit["requested"] for unit in units),
        "scored": sum(unit["scored"] for unit in units),
        "failed": failed,
        "eligible_units": len(units),
        "effective_units": sum(bool(unit["scored"]) for unit in units),
        "raw": {name: metrics["raw_" + name] for name in ("mae", "bias", "rmse")},
        "corrected": {name: metrics["corrected_" + name] for name in ("mae", "bias", "rmse")},
        "reductions": {name: metrics[name + "_reduction"] for name in ("mae", "rmse")},
        "requested_mae_bounds": bounds,
        "units": units,
        "bootstrap": bootstrap(units, key),
    }


def age_stratum(label):
    value = _label(label)
    return "70" if value == 70 else f"{value // 10 * 10}-{value // 10 * 10 + 9}"


def calibrate(rows):
    rows = [row for row in rows if "original" in row.get("roles", ["original"])]
    fit = fit_offset(rows)
    summaries = []
    for group in GROUPS:
        for stratum in STRATA:
            selected = [
                row
                for row in rows
                if row["group"] == group
                and (stratum == "all" or age_stratum(row["source_age_label"]) == stratum)
            ]
            summaries.append(
                {
                    "group": group,
                    "age_stratum": stratum,
                    **summary(selected, fit["offset_years"], f"original/{group}/{stratum}"),
                }
            )
    return {"fit": fit, "summaries": summaries}


def _output(root, name):
    name = name.as_posix() if isinstance(name, Path) else str(name)
    integrity._pin({"path": name, "bytes": 0, "sha256": "0" * 64})
    output = integrity._path(root, name)
    research = (root / "output/research").resolve()
    if root not in research.parents or research not in output.parents or output.exists():
        raise ValueError("Output must be a fresh directory inside ignored output/research.")
    return output


def run(args):
    root = Path(args.root).resolve(strict=True)
    output = _output(root, args.output_dir)
    plan_path = Path(args.study_plan)
    plan_path = (plan_path if plan_path.is_absolute() else root / plan_path).resolve()
    if root not in plan_path.parents or plan_path.suffix.lower() != ".json":
        raise ValueError("Study plan must be workspace JSON metadata.")
    with plan_path.open("rb") as stream:
        plan_bytes = stream.read(LIMIT + 1)
    if len(plan_bytes) > LIMIT:
        raise ValueError("Study plan exceeds its byte bound.")
    plan = _json(plan_bytes)
    runtime = runtime_fingerprint()
    if (
        plan.get("schema_version") != 1
        or plan.get("protocol_id") != PROTOCOL_ID
        or plan.get("runtime") != runtime
        or set(plan.get("roles", {})) != set(ROLES)
    ):
        raise ValueError("Frozen roles, schema or Python runtime differ.")
    roles = {key: integrity._pin(value) for key, value in plan["roles"].items()}
    if any(
        Path(pin["path"]).suffix.lower() != ".json"
        or integrity._path(root, pin["path"]).suffix.lower() != ".json"
        for pin in roles.values()
    ):
        raise ValueError("Each metadata role must name a workspace JSON file.")
    inputs = integrity.Inputs(root, plan.get("inputs"))
    required = {pin["path"] for pin in roles.values()} | set(SOURCES)
    if set(inputs.pins) != required or len(required) != len(ROLES) + len(SOURCES):
        raise ValueError("Freeze must contain exactly six metadata and three source inputs.")
    for source in SOURCES:
        inputs.read(inputs.pins[source])
    if (
        inputs.pins[SOURCES[0]]["sha256"] != LOADED_CODE_SHA256
        or inputs.pins[SOURCES[2]]["sha256"] != integrity.LOADED_CODE_SHA256
    ):
        raise ValueError("Loaded CLI or integrity helper differs from its pinned source.")
    metadata = {key: _json(inputs.read(pin)) for key, pin in roles.items()}
    rows, accounting = parse_records(metadata, roles)
    result = calibrate(rows)

    def recheck():
        inputs.recheck()
        with plan_path.open("rb") as stream:
            current = stream.read(len(plan_bytes) + 1)
        if current != plan_bytes or runtime_fingerprint() != runtime:
            raise ValueError("Study plan or Python runtime drift after calculation.")

    recheck()
    report = {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        **FLAGS,
        "quality_threshold": None,
        "study_plan": {
            "path": plan_path.relative_to(root).as_posix(),
            "bytes": len(plan_bytes),
            "sha256": hashlib.sha256(plan_bytes).hexdigest(),
        },
        "roles": roles,
        "inputs": list(inputs.pins.values()),
        "runtime": runtime,
        "accounting": accounting,
        **result,
        "limitations": metadata["protocol"].get("observations", []),
        "bootstrap_scope": metadata["protocol"]["uncertainty"].get("limitations"),
        "integrity": {
            "all_inputs_unchanged": True,
            "plan_unchanged": True,
            "runtime_unchanged": True,
        },
    }
    data = (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    if len(data) > 8 * LIMIT:
        raise ValueError("Output report exceeds its byte bound.")
    recheck()
    output.mkdir(parents=True, exist_ok=False)
    pending = output / "pending-report.json"
    try:
        with pending.open("xb") as stream:
            stream.write(data)
        recheck()
        pending.rename(output / "report.json")
    except BaseException:
        pending.unlink(missing_ok=True)
        if not any(output.iterdir()):
            output.rmdir()
        raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--study-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    try:
        report = run(parser.parse_args(argv))
        print(
            json.dumps(
                {"offset_years": report["fit"]["offset_years"], "accounting": report["accounting"]},
                ensure_ascii=False,
            )
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

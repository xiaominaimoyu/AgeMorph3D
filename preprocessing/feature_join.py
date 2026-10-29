"""Join P04 declarations with K1-validated saved fits, without inference or training.

python -m preprocessing.feature_join --help
Missing mappings and saved failures stay in the full K5 ledger; no zero filling.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from . import age_features as k1
from . import dataset_manifest as metadata
from . import resource_acquisition as acquisition
from . import split_freeze as freeze

SCHEMA = "agemorph3d-frozen-feature-join-v1"
MAX_JSON = freeze.MAX_JSON
MAX_PLAN = freeze.MAX_PLAN
Error, require, safe = freeze.Error, freeze.require, freeze.safe
_ROOT = Path(__file__).resolve().parents[1]
_SOURCES = {
    name: hashlib.sha256((_ROOT / name).read_bytes()).hexdigest()
    for name in (
        "preprocessing/feature_join.py",
        "preprocessing/age_features.py",
        "preprocessing/split_freeze.py",
        "preprocessing/dataset_manifest.py",
        "preprocessing/duplicate_screening.py",
        "preprocessing/archive_preparation.py",
        "preprocessing/resource_acquisition.py",
        *freeze.screening.ALGORITHM_SOURCES,
    )
}
PRODUCER_SHA256 = _SOURCES["preprocessing/feature_join.py"]
FLAGS = {
    **freeze.FLAGS,
    "training_use": False,
    "production_eligible": False,
    "years_calibrated": False,
    "independent_external_evaluation": False,
    "model_inference_run": False,
    "statistics_fitted": False,
    "standardized": False,
    "identity_centered": False,
    "projection_is_learning_feature": False,
}


def load_frozen(inputs, report_pin, packet_pin):
    """Replay P04 metadata constraints and bind the exact emitted frozen packet."""
    report, packet = inputs.load(report_pin), inputs.load(packet_pin)
    require(
        type(report) is dict
        and report.get("schema_id") == freeze.SCHEMA
        and report.get("producer_sha256") == freeze.PRODUCER_SHA256
        and freeze._same(report.get("dependency_sha256"), freeze._SOURCES)
        and report.get("status") == "consistent"
        and report.get("inputs_stable") is True
        and report.get("research_only") is True
        and report.get("findings") == []
        and report.get("provenance_assessment") == "self_reported_declarations_only"
        and all(report.get(k) is False for k in freeze.FLAGS)
        and report.get("frozen_inputs") == packet_pin,
        "P04_REPORT_NOT_CONSISTENT_OR_VERSION_MISMATCH",
    )
    acquisition._keys(
        packet,
        (
            "schema_id",
            "plan_id",
            "plan_sha256",
            "input_pins",
            "producer_sha256",
            "manifest",
            "assignments",
            "basis",
            "assignment_method",
            "random_seed",
            "provenance_assessment",
            "research_only",
            *freeze.FLAGS,
        ),
    )
    require(
        packet["schema_id"] == freeze.FROZEN_SCHEMA
        and packet["producer_sha256"] == freeze.PRODUCER_SHA256
        and packet["plan_id"] == report.get("plan_id")
        and packet["plan_sha256"] == report.get("plan_sha256")
        and packet["input_pins"] == report.get("inputs")
        and packet["assignment_method"] == "explicit_declarations_only"
        and packet["random_seed"] is None
        and packet["research_only"] is True
        and packet["provenance_assessment"] == "self_reported_declarations_only"
        and all(packet[k] is False for k in freeze.FLAGS),
        "FROZEN_PACKET_BOUNDARY_MISMATCH",
    )
    pins = packet["input_pins"]
    require(type(pins) is list and bool(pins), "P04_INPUTS_MISSING")
    replay = freeze._Inputs(inputs.root)
    plan = acquisition._json(replay.read(pins[0], maximum=freeze.MAX_PLAN))
    acquisition._keys(
        plan,
        (
            "schema_id",
            "plan_id",
            "prepared_manifest",
            "screening_report",
            "basis",
            "assignments",
            "reserve_bytes",
        ),
    )
    require(
        plan["schema_id"] == freeze.SCHEMA
        and plan["plan_id"] == packet["plan_id"]
        and pins[0]["sha256"] == packet["plan_sha256"],
        "P04_PLAN_BINDING_MISMATCH",
    )
    manifest = metadata.validate_manifest(replay.load(plan["prepared_manifest"]))
    require(len(manifest["records"]) <= freeze.preparation.MAX_IMAGES, "FROZEN_RECORD_COUNT_LIMIT")
    source = replay.load(plan["screening_report"])
    rows, candidates, _ = freeze._screening(source, manifest, plan["prepared_manifest"], replay)
    assignments = plan["assignments"]
    require(
        type(assignments) is list and len(assignments) == len(rows),
        "FROZEN_ASSIGNMENT_LEDGER_MISMATCH",
    )
    for item, row in zip(assignments, manifest["records"], strict=True):
        acquisition._keys(item, ("sample_id", "group_id", "use"))
        require(
            item["sample_id"] == row["sample_id"] and metadata._identifier(item["group_id"]),
            "FROZEN_ASSIGNMENT_INVALID",
        )
        require(type(item["use"]) is str and item["use"] in metadata.USES, "FROZEN_USE_INVALID")
    basis = replay.load(plan["basis"])
    groups, reviews = freeze._basis(basis, assignments, candidates, replay)
    require(
        not freeze._constraints(manifest, source, assignments, groups, reviews, candidates),
        "P04_CONSTRAINTS_NO_LONGER_CONSISTENT",
    )
    require(
        freeze._same(packet["manifest"], manifest)
        and packet["assignments"] == assignments
        and packet["basis"] == basis
        and list(replay.pins.values()) == pins,
        "FROZEN_PACKET_CONTENT_MISMATCH",
    )
    expected_rows = [
        {
            "k5": r,
            "assignment": a,
            "screening_status": s["status"],
            "screening_error_code": s["error_code"],
        }
        for r, a, s in zip(manifest["records"], assignments, rows, strict=True)
    ]
    expected_summary = {
        "records": len(rows),
        "groups": len(groups),
        "candidate_reviews": len(reviews),
        "findings": 0,
        "declared_uses": dict(Counter(a["use"] for a in assignments)),
        "formal_split_records": {
            use: sum(a["use"] == use for a in assignments) for use in metadata.FORMAL_USES
        },
    }
    require(
        freeze._same(report.get("records"), expected_rows)
        and freeze._same(report.get("summary"), expected_summary)
        and report.get("basis") == basis
        and freeze._same(report.get("metadata_audit"), metadata.audit_manifest(manifest)),
        "P04_REPORT_CONTENT_MISMATCH",
    )
    for pin in replay.pins.values():
        inputs.read(pin, suffixes=(".json", ".md", ".py"))
    return packet


def load_k1(inputs, report_pin):
    """Use the existing K1 core on its complete seven-JSON saved-fit closure."""
    report = inputs.load(report_pin)
    manifest = inputs.load(report["inputs"]["protocol_manifest"])
    frozen_pin = report["inputs"]["pre_inference_freeze"]
    require(
        k1._pin(frozen_pin) == k1._pin(manifest["inputs"]["pre_inference_freeze"]),
        "K1_FREEZE_BINDING_MISMATCH",
    )
    frozen = inputs.load(frozen_pin)
    for name, pin in manifest["inputs"].items():
        k1._pin(pin)
        if name != "pre_inference_freeze":
            require(frozen["inputs"].get(pin["path"]) == pin["sha256"], "K1_N0_INPUT_PIN_MISMATCH")
    protocol = inputs.load(manifest["inputs"]["protocol"])
    dataset = inputs.load(manifest["inputs"]["dataset_manifest"])
    models = {
        role: inputs.load(report["models"][role]["manifest"])
        for role in ("detector", "reconstructor")
    }
    return k1.build_feature_dataset(report, manifest, frozen, protocol, dataset, models)


def _join_rows(packet, dataset, mappings):
    by_id = {row["sample_id"]: i for i, row in enumerate(dataset["records"])}
    require(
        type(mappings) is list and len(mappings) == len(packet["manifest"]["records"]),
        "MAPPING_LEDGER_MISMATCH",
    )
    selected = []
    for item, row in zip(mappings, packet["manifest"]["records"], strict=True):
        acquisition._keys(item, ("sample_id", "feature_sample_id"))
        require(item["sample_id"] == row["sample_id"], "MAPPING_RECORD_ORDER_MISMATCH")
        sid = item["feature_sample_id"]
        require(sid is None or (type(sid) is str and sid in by_id), "UNKNOWN_FEATURE_SAMPLE_ID")
        if sid is not None:
            require(sid not in selected, "FEATURE_MAPPING_REUSED")
            selected.append(sid)
    records, indices, shape, expression, projection = [], [], [], [], []
    for k5, assignment, mapping in zip(
        packet["manifest"]["records"], packet["assignments"], mappings, strict=True
    ):
        index = by_id.get(mapping["feature_sample_id"])
        source = None if index is None else dataset["records"][index]
        row = {
            "k5": copy.deepcopy(k5),
            "assignment": copy.deepcopy(assignment),
            "mapping": copy.deepcopy(mapping),
            "status": "failed",
            "error_code": None,
            "feature_row_index": None,
            "k1_record_index": index,
            "source_record": copy.deepcopy(source),
            "source_error_code": None if source is None else source["error_code"],
        }
        try:
            require(source is not None, "NO_SAVED_FEATURE_MAPPING")
            require(k5["kind"] == "original" and k5["parent_id"] is None, "ORIGINAL_PHOTO_REQUIRED")
            require(
                k1._pin(k5["file"]) == source["original_image"],
                "ORIGINAL_IMAGE_DECLARATION_MISMATCH",
            )
            require(k5["subject_id"] == source["subject_id"], "SUBJECT_DECLARATION_MISMATCH")
            require(k5["use"] == assignment["use"] == source["group"], "SOURCE_USE_MISMATCH")
            require(
                freeze._same(
                    k5["age"],
                    {k: source["research_age"][k] for k in ("kind", "value", "lower", "upper")},
                ),
                "AGE_DECLARATION_MISMATCH",
            )
            require(source["fit_status"] == "ok", "SOURCE_FIT_FAILED")
            source_index = source["feature_row_index"]
            row.update(status="joined", feature_row_index=len(shape))
            indices.append(len(records))
            shape.append(copy.deepcopy(dataset["features"]["shape"][source_index]))
            expression.append(copy.deepcopy(dataset["features"]["expression"][source_index]))
            projection.append(copy.deepcopy(dataset["features"]["projection"][source_index]))
        except Error as error:
            row["error_code"] = str(error)
        records.append(row)
    return (
        records,
        {
            "record_indices": indices,
            "shape": shape,
            "expression": expression,
            "projection": projection,
        },
        selected,
    )


def join(root, plan_name, plan_sha256, output):
    root = Path(root).absolute()
    require(
        root.is_dir() and root == root.resolve() and acquisition._sha(plan_sha256),
        "INVALID_ROOT_OR_PLAN_PIN",
    )
    body = acquisition._read(safe(root, plan_name), MAX_PLAN)
    require(hashlib.sha256(body).hexdigest() == plan_sha256, "PLAN_SHA256_MISMATCH")
    inputs = freeze._Inputs(root)
    inputs.read({"path": plan_name, "bytes": len(body), "sha256": plan_sha256}, maximum=MAX_PLAN)
    plan = acquisition._json(body)
    acquisition._keys(
        plan,
        (
            "schema_id",
            "plan_id",
            "precheck_report",
            "frozen_inputs",
            "feature_report",
            "expected_binding",
            "mappings",
            "reserve_bytes",
        ),
    )
    require(
        plan["schema_id"] == SCHEMA and acquisition._identifier(plan["plan_id"]), "INVALID_PLAN"
    )
    require(acquisition._integer(plan["reserve_bytes"], 0, 64 * 1024**3), "INVALID_RESERVE")
    packet = load_frozen(inputs, plan["precheck_report"], plan["frozen_inputs"])
    dataset = load_k1(inputs, plan["feature_report"])
    require(
        freeze._same(dataset["binding"], plan["expected_binding"]),
        "FEATURE_MODEL_BASIS_TOPOLOGY_BINDING_MISMATCH",
    )
    rows, features, selected = _join_rows(packet, dataset, plan["mappings"])
    before_check = len(features["shape"])
    changed = inputs.changed()
    for name, digest in _SOURCES.items():
        try:
            require(
                hashlib.sha256((_ROOT / name).read_bytes()).hexdigest() == digest, "SOURCE_CHANGED"
            )
        except (Error, OSError):
            changed.append(name)
    if changed:
        for row in rows:
            row.update(
                previous_join_status=row["status"],
                previous_error_code=row["error_code"],
                status="failed",
                error_code="INPUT_CHANGED_AT_FINAL_CHECK",
                feature_row_index=None,
            )
        features = {key: [] for key in features}
    report = {
        "schema_id": SCHEMA,
        "plan_id": plan["plan_id"],
        "plan_sha256": plan_sha256,
        "producer_sha256": PRODUCER_SHA256,
        "dependency_sha256": _SOURCES,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "inputs": list(inputs.pins.values()),
        "inputs_stable": not changed,
        "changed_inputs": sorted(set(changed)),
        "research_only": True,
        "provenance_assessment": "saved_metadata_and_self_reported_declarations_only",
        "binding": dataset["binding"],
        "records": rows,
        "features": features,
        "source_summary": dataset["summary"],
        "source_dataset_provenance": dataset["dataset_provenance"],
        "unmapped_source_records": [
            {
                "sample_id": r["sample_id"],
                "fit_status": r["fit_status"],
                "error_code": r["error_code"],
            }
            for r in dataset["records"]
            if r["sample_id"] not in selected
        ],
        "summary": {
            "requested": len(rows),
            "joined": len(features["shape"]),
            "failed": len(rows) - len(features["shape"]),
            "feature_rows_before_final_check": before_check,
            "failure_codes": dict(
                Counter(r["error_code"] for r in rows if r["status"] == "failed")
            ),
            "uses": dict(Counter(r["k5"]["use"] for r in rows)),
        },
        "metadata_audit": metadata.audit_manifest(packet["manifest"]),
        **FLAGS,
    }
    report["status"] = "passed" if not changed and report["summary"]["failed"] == 0 else "failed"
    payload = acquisition._encoded(report)
    require(len(payload) <= MAX_JSON, "REPORT_TOO_LARGE")
    target = safe(root, output)
    require(output.startswith("output/research/") and not target.exists(), "OUTPUT_MUST_BE_NEW")
    require(shutil.disk_usage(root).free >= plan["reserve_bytes"] + MAX_JSON, "INSUFFICIENT_SPACE")
    target.mkdir(parents=True, exist_ok=False)
    with safe(root, output + "/report.json").open("xb") as stream:
        stream.write(payload)
    return {**report, "receipt": output + "/report.json"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        report = join(args.root, args.plan, args.plan_sha256, args.output_dir)
    except (Error, OSError, ValueError, KeyError, TypeError, OverflowError, IndexError) as error:
        code = str(error) if isinstance(error, Error) else "INPUT_REJECTED"
        print(json.dumps({"status": "rejected", "error_code": code, **FLAGS}))
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())

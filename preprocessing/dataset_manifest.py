"""Age-data metadata contract and declared-use audit; no image reads or training.

Run from the project root: python -m preprocessing.dataset_manifest --help
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

SCHEMA = "agemorph3d-dataset-manifest-v1"
TASK = "age_morph_20_70"
MAX_JSON_BYTES = 16 * 1024**2
MAX_RECORDS = 100_000
RESEARCH_USES = ("development", "calibration_research", "evaluation_research_holdout")
FORMAL_USES = ("train", "validation", "test")
USES = ("unassigned", *RESEARCH_USES, *FORMAL_USES)
FLAGS = dict.fromkeys(
    (
        "formal_dataset_ready",
        "training_authorized",
        "independent_evaluation",
        "service_ready",
        "production_enabled",
        "g3_complete",
    ),
    False,
)
_PRODUCER_PATH = Path(__file__).resolve()
_PRODUCER_HASH = hashlib.sha256(_PRODUCER_PATH.read_bytes()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _keys(value, keys):
    _require(type(value) is dict and set(value) == set(keys), "Unexpected or missing fields.")


def _identifier(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value)


def _path(name):
    _require(type(name) is str and bool(name), "Invalid declared relative path.")
    path = PurePosixPath(name)
    _require(
        not path.is_absolute()
        and path.as_posix() == name
        and all(ord(c) >= 32 for c in name)
        and "\\" not in name
        and ":" not in name
        and not {"..", "."} & set(path.parts),
        "Noncanonical or external path.",
    )
    return name


def _pin(value):
    _keys(value, ("path", "bytes", "sha256"))
    _path(value["path"])
    _require(type(value["bytes"]) is int and value["bytes"] > 0, "Invalid declared byte count.")
    _require(
        type(value["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]),
        "Invalid declared SHA-256.",
    )


def age_label(kind, value=None, *, lower=None, upper=None):
    def number(v):
        return type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 120

    if kind == "exact":
        _require(number(value) and lower is upper is None, "Invalid exact raw age.")
    elif kind == "interval":
        _require(
            value is None and number(lower) and number(upper) and lower < upper,
            "Invalid raw age interval.",
        )
    else:
        _require(
            kind == "unknown" and value is lower is upper is None, "Unknown age must remain null."
        )
    return {"kind": kind, "value": value, "lower": lower, "upper": upper}


def _registration(value, statuses):
    _keys(value, ("status", "evidence"))
    _require(
        type(value["status"]) is str and value["status"] in statuses,
        "Invalid registration/review status.",
    )
    if value["evidence"] is not None:
        _pin(value["evidence"])
    _require(
        value["status"] in {"unresolved", "pending", "unknown"} or value["evidence"] is not None,
        "Recorded claims require a declared evidence pin.",
    )


def validate_manifest(manifest):
    """Validate and detach the full metadata packet, retaining order and failures."""
    _keys(
        manifest,
        ("schema_id", "schema_version", "task", "manifest_id", "origin", "datasets", "records"),
    )
    _require(
        manifest["schema_id"] == SCHEMA
        and type(manifest["schema_version"]) is int
        and manifest["schema_version"] == 1
        and manifest["task"] == TASK
        and _identifier(manifest["manifest_id"]),
        "Unsupported age dataset manifest.",
    )
    if manifest["origin"] is not None:
        _pin(manifest["origin"])
    datasets, records = manifest["datasets"], manifest["records"]
    _require(type(datasets) is list and 1 <= len(datasets) <= 128, "Invalid dataset count.")
    _require(type(records) is list and 1 <= len(records) <= MAX_RECORDS, "Invalid record count.")
    dataset_ids = set()
    for dataset in datasets:
        _keys(
            dataset,
            (
                "dataset_id",
                "version",
                "purpose_registration",
                "identity_review",
                "training_overlap",
                "near_duplicate_review",
            ),
        )
        _require(
            _identifier(dataset["dataset_id"]) and dataset["dataset_id"] not in dataset_ids,
            "Duplicate/invalid dataset identifier.",
        )
        dataset_ids.add(dataset["dataset_id"])
        _require(
            type(dataset["version"]) is str and 0 < len(dataset["version"].strip()) <= 200,
            "Missing dataset version.",
        )
        for field, statuses in (
            ("purpose_registration", {"unresolved", "recorded"}),
            ("identity_review", {"pending", "recorded"}),
            ("training_overlap", {"unknown", "excluded", "present"}),
            ("near_duplicate_review", {"pending", "recorded"}),
        ):
            _registration(dataset[field], statuses)
    ids = set()
    for row in records:
        _keys(
            row,
            (
                "sample_id",
                "dataset_id",
                "file",
                "subject_id",
                "linked_subject_id",
                "parent_id",
                "kind",
                "use",
                "age",
                "age_source",
                "exposure",
                "processing",
            ),
        )
        _require(
            _identifier(row["sample_id"]) and row["sample_id"] not in ids,
            "Duplicate/invalid sample ID.",
        )
        ids.add(row["sample_id"])
        _require(
            type(row["dataset_id"]) is str and row["dataset_id"] in dataset_ids,
            "Unknown dataset reference.",
        )
        _pin(row["file"])
        _require(
            PurePosixPath(row["file"]["path"]).suffix.lower()
            in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"},
            "Record must declare an image path.",
        )
        for field in ("subject_id", "linked_subject_id", "parent_id"):
            _require(row[field] is None or _identifier(row[field]), "Invalid identity/parent ID.")
        _require(
            type(row["kind"]) is str and row["kind"] in {"original", "crop", "generated", "render"},
            "Invalid image kind.",
        )
        _require(
            (row["parent_id"] is None) == (row["kind"] == "original"),
            "Derived images need an included parent; originals have none.",
        )
        _require(type(row["use"]) is str and row["use"] in USES, "Invalid declared use.")
        _keys(row["age"], ("kind", "value", "lower", "upper"))
        age_label(**row["age"])
        _require(
            type(row["age_source"]) is str
            and row["age_source"]
            in {"filename_research", "dataset_annotation", "user_statement", "unknown"},
            "Invalid age provenance.",
        )
        _require(
            row["age"]["kind"] == "unknown" or row["age_source"] != "unknown",
            "Known labels need a source declaration.",
        )
        _keys(row["exposure"], ("preprocessing", "model_selection", "result_inspection"))
        _require(
            all(type(v) is str and v in {"yes", "no", "unknown"} for v in row["exposure"].values()),
            "Exposure must distinguish yes/no/unknown.",
        )
        _keys(row["processing"], ("status", "reason"))
        status, reason = row["processing"]["status"], row["processing"]["reason"]
        _require(
            type(status) is str and status in {"not_checked", "ok", "failed", "excluded"},
            "Invalid processing status.",
        )
        _require(
            (type(reason) is str and 0 < len(reason.strip()) <= 1000)
            if status in {"failed", "excluded"}
            else reason is None,
            "Failures/exclusions need reasons; unchecked records are not success.",
        )
    by_id = {r["sample_id"]: r for r in records}
    done = set()
    for row in records:
        chain, current = set(), row["sample_id"]
        while current is not None and current not in done:
            _require(current in by_id and current not in chain, "Missing or cyclic parent lineage.")
            chain.add(current)
            current = by_id[current]["parent_id"]
        done.update(chain)
    return copy.deepcopy(manifest)


def audit_manifest(value):
    """Audit declarations only; never assign splits or authorize training."""
    manifest = validate_manifest(value)
    rows = manifest["records"]
    parents = {r["sample_id"]: r["sample_id"] for r in rows}

    def find(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parents[max(a, b)] = min(a, b)

    identities = {}
    hashes, paths = defaultdict(list), defaultdict(list)
    for row in rows:
        sid = row["sample_id"]
        keys = []
        if row["subject_id"] is not None:
            keys.append(("local", row["dataset_id"], row["subject_id"]))
        if row["linked_subject_id"] is not None:
            keys.append(("linked", row["linked_subject_id"]))
        for key in keys:
            if key in identities:
                union(sid, identities[key])
            else:
                identities[key] = sid
        if row["parent_id"] is not None:
            union(sid, row["parent_id"])
        hashes[row["file"]["sha256"]].append(row)
        paths[row["file"]["path"]].append(row)
    components = defaultdict(list)
    for row in rows:
        components[find(row["sample_id"])].append(row)
    findings = []

    def add(code, selected=(), dataset_id=None):
        item = {"code": code, "sample_ids": sorted(r["sample_id"] for r in selected)}
        if dataset_id is not None:
            item["dataset_id"] = dataset_id
        findings.append(item)

    def uses(group):
        return {r["use"] for r in group} - {"unassigned"}

    for group in components.values():
        if len(uses(group)) > 1:
            add("IDENTITY_OR_LINEAGE_CROSSES_USES", group)
    for group in hashes.values():
        if len(uses(group)) > 1:
            add("DECLARED_DUPLICATE_CONTENT_CROSSES_USES", group)
        if len({r["file"]["bytes"] for r in group}) > 1:
            add("DECLARED_HASH_SIZE_CONFLICT", group)
    for group in paths.values():
        if len({(r["file"]["sha256"], r["file"]["bytes"]) for r in group}) > 1:
            add("DECLARED_PATH_CONTENT_CONFLICT", group)
    defined = {r["use"] for r in rows}
    if not set(FORMAL_USES) <= defined:
        add("FORMAL_SPLITS_NOT_DEFINED")
    for dataset in manifest["datasets"]:
        did = dataset["dataset_id"]
        selected = [r for r in rows if r["dataset_id"] == did]
        for field, expected, code in (
            ("purpose_registration", "recorded", "USE_REGISTRATION_UNRESOLVED"),
            ("identity_review", "recorded", "IDENTITY_REVIEW_PENDING"),
            ("near_duplicate_review", "recorded", "NEAR_DUPLICATE_REVIEW_PENDING"),
        ):
            if dataset[field]["status"] != expected:
                add(code, selected, did)
        tests = [r for r in selected if r["use"] == "test"]
        if dataset["training_overlap"]["status"] == "unknown":
            add("TRAINING_OVERLAP_UNRESOLVED", selected, did)
        if tests and dataset["training_overlap"]["status"] != "excluded":
            add("TEST_TRAINING_OVERLAP_NOT_EXCLUDED", tests, did)
    checks = []
    bins = Counter()
    for row in rows:
        label, code = row["age"], "unknown"
        if label["kind"] == "exact":
            age = label["value"]
            code = "inside" if 20 <= age <= 70 else "outside"
            if code == "inside":
                bins["70" if age == 70 else f"{int(age // 10) * 10}-{int(age // 10) * 10 + 9}"] += 1
        elif label["kind"] == "interval":
            code = (
                "inside" if 20 <= label["lower"] < label["upper"] <= 70 else "outside_or_crossing"
            )
        checks.append(
            {
                "sample_id": row["sample_id"],
                "use": row["use"],
                "age_scope": code,
                "processing": row["processing"],
                "declared_content_verified": False,
            }
        )
        if row["use"] in FORMAL_USES:
            if row["subject_id"] is row["linked_subject_id"] is None:
                add("FORMAL_IDENTITY_UNRESOLVED", [row])
            if code != "inside":
                add("FORMAL_AGE_OUTSIDE_OR_UNRESOLVED", [row])
            if row["processing"]["status"] != "ok":
                add("FORMAL_PROCESSING_NOT_VERIFIED", [row])
        if row["use"] in {"validation", "test"} and row["kind"] in {"generated", "render"}:
            add("GENERATED_IMAGE_IS_NOT_AGE_GROUND_TRUTH", [row])
        if row["use"] == "test" and any(v != "no" for v in row["exposure"].values()):
            add("TEST_EXPOSURE_NOT_CLEAR", [row])
    return {
        "schema_id": SCHEMA,
        "status": "completed_with_findings" if findings else "metadata_consistent",
        "summary": {
            "records": len(rows),
            "datasets": len(manifest["datasets"]),
            "local_subjects": len(
                {(r["dataset_id"], r["subject_id"]) for r in rows if r["subject_id"] is not None}
            ),
            "unknown_subject_records": sum(
                r["subject_id"] is r["linked_subject_id"] is None for r in rows
            ),
            "uses": dict(Counter(r["use"] for r in rows)),
            "formal_split_records": {
                use: sum(r["use"] == use for r in rows) for use in FORMAL_USES
            },
            "processing": dict(Counter(r["processing"]["status"] for r in rows)),
            "age_kinds": dict(Counter(r["age"]["kind"] for r in rows)),
            "exact_age_bins_20_70": dict(sorted(bins.items())),
            "declared_duplicate_groups": sum(len(g) > 1 for g in hashes.values()),
            "findings": len(findings),
        },
        "findings": findings,
        "record_checks": checks,
        "binary_integrity_verified": False,
        "cross_source_identity_proven": False,
        "near_duplicates_recomputed": False,
        "permission_assessment": "registration_only",
        "split_assignment_performed": False,
        "model_inference_run": False,
        **FLAGS,
    }


def from_n0(value, origin):
    """Convert all saved adult metadata, not images or holdout predictions."""
    _pin(origin)
    _require(
        type(value.get("schema_version")) is int
        and value.get("schema_version") == 1
        and value.get("protocol_id") == "agemorph3d-age-research-v1"
        and value.get("research_only") is True
        and value.get("historical_preprocessing_exposed") is True
        and all(
            value.get(k) is False
            for k in (
                "training_use",
                "service_ready",
                "g3_complete",
                "independent_external_evaluation",
            )
        ),
        "Only the closed N0 research manifest can be converted.",
    )
    identities = value["identities"]
    groups = {r["subject_id"]: r["group"] for r in identities}
    _require(
        len(groups) == len(identities) == value["summary"]["adult_identities"],
        "N0 identity denominator changed.",
    )
    _require(
        all(
            r["historical_preprocessing_exposed"] is True and r["group"] in RESEARCH_USES
            for r in identities
        ),
        "N0 exposure/group declaration differs.",
    )
    failures = {}
    for case in value["bridge_cases"]:
        if case["source_status"] == "failed":
            _require(_identifier(case["error_code"]), "Historical failure code is missing.")
            _pin(case["source"])
            _require(case["source"]["path"] not in failures, "Duplicate historical failure record.")
            failures[case["source"]["path"]] = case
    blocked_count = value["summary"]["control_statuses"]["blocked_source_failure"]
    _require(
        type(blocked_count) is int and len(failures) == blocked_count,
        "N0 historical failed-source denominator changed.",
    )
    rows, seen = [], set()
    for row in value["adult_images"]:
        file = {k: row[k] for k in ("path", "bytes", "sha256")}
        _pin(file)
        match = re.fullmatch(
            r"(\d{3})A(\d{2})[A-Za-z]?\.JPG", PurePosixPath(file["path"]).name, re.I
        )
        _require(
            match
            and match[1] == row["subject_id"]
            and type(row["source_age"]) is int
            and int(match[2]) == row["source_age"]
            and 20 <= row["source_age"] <= 70
            and groups.get(row["subject_id"]) == row["group"]
            and file["path"] not in seen,
            "N0 row identity, age, group or unique path changed.",
        )
        seen.add(file["path"])
        failure = failures.get(file["path"])
        if failure:
            _require(
                failure["source"] == file
                and failure["subject_id"] == row["subject_id"]
                and failure["group"] == row["group"],
                "N0 historical failure binding differs.",
            )
        rows.append(
            {
                "sample_id": "fgnet--" + PurePosixPath(file["path"]).stem.lower(),
                "dataset_id": "fgnet-n0",
                "file": file,
                "subject_id": row["subject_id"],
                "linked_subject_id": None,
                "parent_id": None,
                "kind": "original",
                "use": row["group"],
                "age": age_label("exact", row["source_age"]),
                "age_source": "filename_research",
                "exposure": {
                    "preprocessing": "yes",
                    "model_selection": "unknown",
                    "result_inspection": "unknown",
                },
                "processing": {
                    "status": "failed" if failure else "not_checked",
                    "reason": "historical_bridge:" + failure["error_code"] if failure else None,
                },
            }
        )
    _require(
        len(rows) == value["summary"]["adult_images"]
        and set(groups) == {r["subject_id"] for r in rows}
        and not set(failures) - seen,
        "N0 image/failure denominator changed.",
    )
    _require(
        dict(Counter(groups.values())) == value["summary"]["identity_groups"]
        and dict(Counter(r["use"] for r in rows)) == value["summary"]["image_groups"],
        "N0 frozen use-group counts changed.",
    )
    dataset = {
        "dataset_id": "fgnet-n0",
        "version": "N0:" + value["frozen_on"],
        "purpose_registration": {"status": "unresolved", "evidence": None},
        "identity_review": {"status": "pending", "evidence": None},
        "training_overlap": {"status": "unknown", "evidence": None},
        "near_duplicate_review": {"status": "pending", "evidence": None},
    }
    return validate_manifest(
        {
            "schema_id": SCHEMA,
            "schema_version": 1,
            "task": TASK,
            "manifest_id": "fgnet-n0-metadata-v1",
            "origin": origin,
            "datasets": [dataset],
            "records": rows,
        }
    )


def _json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "Duplicate JSON key.")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("Nonfinite JSON value.")

    return json.loads(data, object_pairs_hook=pairs, parse_constant=nonfinite)


def _encode(value):
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, indent=2) + "\n").encode()


def _resolve(root, name):
    path = root / _path(name)
    _require(path.resolve().is_relative_to(root.resolve()), "Path escapes workspace.")
    return path


def _read(path, limit=MAX_JSON_BYTES):
    _require(
        path.is_file() and path.stat().st_size <= limit, "Input is missing/nonregular/oversized."
    )
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    _require(len(data) <= limit, "Input grew beyond its read budget.")
    return data


def export_manifest(root, name, expected_sha256, output, *, n0=False):
    """Only the selected JSON and this producer are read; image pins stay declared."""
    root = root.resolve()
    source = _resolve(root, name)
    _require(source.suffix.lower() == ".json", "Select a JSON metadata file.")
    data = _read(source)
    pin = {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    _pin(pin)
    _require(pin["sha256"] == expected_sha256, "Input SHA-256 mismatch.")
    value = _json(data)
    manifest = from_n0(value, pin) if n0 else validate_manifest(value)
    report = audit_manifest(manifest)
    report.update(inputs=[pin], producer_sha256=_PRODUCER_HASH, python=sys.version)
    payloads = {"manifest.json": _encode(manifest), "audit.json": _encode(report)}
    _require(
        all(len(raw) <= MAX_JSON_BYTES for raw in payloads.values()),
        "Output JSON exceeds the metadata byte budget.",
    )
    target = _resolve(root, output)
    _require(
        output.startswith("output/research/"), "Use a fresh ignored research output directory."
    )
    _require(
        target != source and not source.is_relative_to(target),
        "Output must not contain its own input.",
    )

    def recheck():
        _require(
            _read(source, len(data)) == data
            and hashlib.sha256(_PRODUCER_PATH.read_bytes()).hexdigest() == _PRODUCER_HASH,
            "Input or producer changed during audit.",
        )

    recheck()
    target.mkdir(parents=True, exist_ok=False)
    owned = []
    try:
        for leaf, raw in payloads.items():
            path = target / leaf
            with path.open("xb") as stream:
                owned.append(path)
                stream.write(raw)
        recheck()
    except BaseException:
        for path in reversed(owned):
            path.unlink()
        if not any(target.iterdir()):
            target.rmdir()
        raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--manifest")
    modes.add_argument("--n0-manifest")
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        report = export_manifest(
            _PRODUCER_PATH.parents[1],
            args.manifest or args.n0_manifest,
            args.sha256,
            args.output_dir,
            n0=args.n0_manifest is not None,
        )
    except (ValueError, OSError, KeyError, TypeError, IndexError) as error:
        print(
            json.dumps({"status": "invalid_input", "error": str(error), **FLAGS}), file=sys.stderr
        )
        return 2
    print(json.dumps({"status": report["status"], "summary": report["summary"], **FLAGS}))
    return 1 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

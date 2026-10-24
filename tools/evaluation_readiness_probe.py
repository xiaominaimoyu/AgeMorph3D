"""Audit pinned N8 metadata without opening photographs, weights or age results.

Exit zero means the bounded metadata audit executed; it never grants permission,
loads a model, accepts quality, or enables a production capability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import urlsplit

PROTOCOL = "agemorph3d-evaluation-readiness-v1"
N0_PROTOCOL = "agemorph3d-age-research-v1"
ASSETS = (
    "detector",
    "reconstructor",
    "bfm_source",
    "sam_generator",
    "fgnet_dataset",
    "agedb_dataset",
    "age_evaluator",
    "identity_evaluator",
    "derived_assets",
)
DIMENSIONS = ("code", "weights", "training_data", "derived_distribution")
SOURCE_FILES = (
    "tools/evaluation_readiness_probe.py",
    "backend/tests/test_evaluation_readiness_probe.py",
)
STRATA = ("20-29", "30-39", "40-49", "50-59", "60-69", "70")
GROUPS = ("development", "calibration_research", "evaluation_research_holdout")
MAX_BYTES = 2 * 1024 * 1024
SUFFIXES = {".json", ".md", ".ts", ".py", ".mjs"}
FALSE_FLAGS = (
    "production_enabled",
    "g3_complete",
    "service_ready",
    "age_quality_accepted",
    "identity_quality_accepted",
)


def _keys(value, expected, label):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError(f"{label} fields differ from the supported schema.")


def _text(value, label, limit=4000):
    if type(value) is not str or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"{label} must be bounded nonempty text.")
    return value


def _integer(value, label, minimum=0, maximum=10000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be a bounded integer.")
    return value


def _list(value, label, maximum=128):
    if type(value) is not list or len(value) > maximum:
        raise ValueError(f"{label} must be a bounded list.")
    return value


def _relative(root, value):
    value = _text(value, "Metadata path", 1000)
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    if (
        "\\" in value
        or ":" in value
        or windows.drive
        or windows.root
        or posix.is_absolute()
        or posix.as_posix() != value
        or any(part in {".", "..", ""} for part in value.split("/"))
    ):
        raise ValueError("Paths must be canonical workspace-relative POSIX paths.")
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Metadata path resolves outside the workspace.")
    return path


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON keys are forbidden.")
        value[key] = item
    return value


def _read(path):
    if path.suffix.lower() not in SUFFIXES:
        raise ValueError("Only JSON/MD/TS/PY/MJS metadata may be read; no images or weights.")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if not 0 < len(raw) <= MAX_BYTES:
        raise ValueError("Metadata must be nonempty and no larger than 2 MiB.")
    raw.decode("utf-8")
    if path.suffix.lower() == ".json":
        _json(raw)
    return raw


def _json(raw):
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON.")),
        )
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Metadata is not bounded UTF-8 JSON.") from error
    if type(value) is not dict:
        raise ValueError("Metadata JSON must have an object root.")
    return value


def _pin_value(root, pin):
    _keys(pin, {"path", "sha256", "bytes"}, "Pin")
    path = _relative(root, pin["path"])
    if type(pin["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]):
        raise ValueError("Pin SHA-256 must be lowercase hexadecimal.")
    _integer(pin["bytes"], "Pin bytes", 1, MAX_BYTES)
    if path.suffix.lower() not in SUFFIXES:
        raise ValueError("A pin may reference metadata only; no images or weights.")
    return path


class _Inputs:
    def __init__(self, root):
        self.root = root
        self.pins = {}

    def read(self, pin):
        path = _pin_value(self.root, pin)
        if pin["path"] not in self.pins and len(self.pins) >= 128:
            raise ValueError("At most 128 distinct metadata inputs are supported.")
        if pin["path"] in self.pins and self.pins[pin["path"]] != pin:
            raise ValueError("Conflicting pins reference the same metadata path.")
        raw = _read(path)
        if len(raw) != pin["bytes"] or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
            raise ValueError(f"Metadata pin mismatch: {pin['path']}")
        self.pins[pin["path"]] = dict(pin)
        return raw

    def many(self, pins, label):
        paths = set()
        for pin in _list(pins, label):
            path = _pin_value(self.root, pin)
            if path in paths:
                raise ValueError(f"Duplicate pin in {label}.")
            paths.add(path)
            self.read(pin)

    def verify(self):
        for pin in list(self.pins.values()):
            self.read(pin)


def _https(value):
    value = _text(value, "Source URL", 2000)
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(character.isspace() for character in value)
            or (port is not None and not 1 <= port <= 65535)
        ):
            raise ValueError("invalid URL")
    except ValueError as error:
        raise ValueError("Source URLs must be valid HTTPS URLs without credentials.") from error


def _catalog(value, inputs):
    _keys(value, {"schema_version", "protocol_id", "reviewed_on", "scope", "assets"}, "Catalog")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("Catalog schema_version must be integer 1.")
    if value["protocol_id"] != PROTOCOL:
        raise ValueError("Catalog protocol is unsupported.")
    reviewed = _text(value["reviewed_on"], "Review date", 10)
    if date.fromisoformat(reviewed).isoformat() != reviewed:
        raise ValueError("Review date must be YYYY-MM-DD.")
    _text(value["scope"], "Catalog scope")
    assets, seen = [], set()
    for asset in _list(value["assets"], "Assets", len(ASSETS)):
        _keys(
            asset,
            {
                "asset_id",
                "acquisition_state",
                "local_metadata",
                "licenses",
                "independence",
                "next_action",
            },
            "Asset",
        )
        asset_id = asset["asset_id"]
        if type(asset_id) is not str or asset_id not in ASSETS or asset_id in seen:
            raise ValueError("Asset IDs must be unique and supported.")
        seen.add(asset_id)
        acquisition = asset["acquisition_state"]
        if acquisition not in {"metadata_present", "not_acquired"}:
            raise ValueError("Unsupported acquisition state.")
        metadata = _list(asset["local_metadata"], "Local metadata")
        if bool(metadata) != (acquisition == "metadata_present"):
            raise ValueError("Acquisition state and local metadata disagree.")
        inputs.many(metadata, f"{asset_id} local metadata")
        _keys(asset["licenses"], DIMENSIONS, "License dimensions")
        for dimension, license_item in asset["licenses"].items():
            _keys(license_item, {"status", "evidence", "source_urls", "reason"}, "License item")
            status = license_item["status"]
            if status not in {
                "missing",
                "unresolved",
                "restricted",
                "documented",
                "not_applicable",
            }:
                raise ValueError("Unsupported license status.")
            evidence = _list(license_item["evidence"], "License evidence")
            if status == "documented" and not evidence:
                raise ValueError(f"Documented {asset_id}/{dimension} needs pinned evidence.")
            inputs.many(evidence, f"{asset_id}/{dimension} evidence")
            urls = _list(license_item["source_urls"], "License URLs", 32)
            if len(urls) != len(set(_text(url, "Source URL", 2000) for url in urls)):
                raise ValueError("Duplicate source URLs are forbidden.")
            for url in urls:
                _https(url)
            _text(license_item["reason"], "License reason")
        if asset_id.endswith("_evaluator"):
            if asset["independence"] not in {
                "not_assessed",
                "sam_training_loss",
                "separate_candidate",
            }:
                raise ValueError("Evaluator independence must be explicit.")
        elif asset["independence"] is not None:
            raise ValueError("Non-evaluator independence must be null.")
        _text(asset["next_action"], "Next action")
        assets.append(asset)
    if seen != set(ASSETS):
        raise ValueError("Catalog must contain exactly the nine required assets.")
    return assets


def _false_flags(value, fields, label):
    if any(value.get(field) is not False for field in fields):
        raise ValueError(f"{label} must retain the research-only false flags.")


def _n0(protocol, manifest, summary, protocol_pin):
    if protocol.get("protocol_id") != N0_PROTOCOL or manifest.get("protocol_id") != N0_PROTOCOL:
        raise ValueError("Only the frozen N0 v1 metadata protocol is supported.")
    if any(
        type(value.get("schema_version")) is not int or value["schema_version"] != 1
        for value in (protocol, manifest)
    ):
        raise ValueError("N0 schema_version must be integer 1.")
    if (
        protocol.get("source_age_policy") != "unknown_stays_null"
        or protocol.get("same_age_policy") != "exact_integer_label_only"
        or protocol.get("target_ages") != [20, 45, 70]
        or protocol.get("statistics", {}).get("age_strata") != list(STRATA)
        or manifest.get("inputs", {}).get("protocol") != protocol_pin
        or manifest.get("summary") != summary
    ):
        raise ValueError("N0 policy, protocol pin or independent summary differs.")
    _false_flags(
        protocol,
        ("service_ready", "years_calibrated", "identity_accepted", "g3_complete"),
        "N0 protocol",
    )
    _false_flags(
        manifest,
        (
            "training_use",
            "service_ready",
            "g3_complete",
            "independent_external_evaluation",
            "independent_landmark_nme_evaluation",
        ),
        "N0 manifest",
    )
    grouping = protocol.get("grouping", {})
    if (
        manifest.get("research_only") is not True
        or manifest.get("historical_preprocessing_exposed") is not True
        or grouping.get("historical_preprocessing_exposed") is not True
        or grouping.get("independent_external_evaluation") is not False
    ):
        raise ValueError("N0 exposure and research-only metadata are required.")
    identities = _list(manifest.get("identities"), "N0 identities", 5000)
    groups, viewed = {}, set()
    for identity in identities:
        subject, group = identity.get("subject_id"), identity.get("group")
        if (
            type(subject) is not str
            or not re.fullmatch(r"[0-9]{3}", subject)
            or subject in groups
            or group not in GROUPS
            or identity.get("historical_preprocessing_exposed") is not True
            or type(identity.get("previously_viewed")) is not bool
            or (identity["previously_viewed"] and group != "development")
        ):
            raise ValueError("Invalid N0 identity, exposure or viewed-use metadata.")
        groups[subject] = group
        if identity["previously_viewed"]:
            viewed.add(subject)
    development = _list(grouping.get("development_subject_ids"), "N0 development IDs", 5000)
    if (
        len(development) != len(set(development))
        or set(development)
        != {subject for subject, group in groups.items() if group == "development"}
        or not viewed <= set(development)
        or sum(group == "calibration_research" for group in groups.values())
        != _integer(grouping.get("calibration_identity_count"), "Calibration count")
    ):
        raise ValueError("N0 frozen identity uses differ from the protocol.")
    seed = _text(grouping.get("seed"), "N0 grouping seed", 200)
    remaining = sorted(
        set(groups) - set(development),
        key=lambda subject: hashlib.sha256(f"{seed}:{subject}".encode()).hexdigest(),
    )
    expected_calibration = set(remaining[: grouping["calibration_identity_count"]])
    if expected_calibration != {
        subject for subject, group in groups.items() if group == "calibration_research"
    }:
        raise ValueError("N0 frozen assignments differ from deterministic protocol verification.")
    rows = _list(manifest.get("adult_images"), "N0 image metadata", 10000)
    paths, digest_groups, by_subject = set(), {}, {}
    for row in rows:
        subject, age, group = row.get("subject_id"), row.get("source_age"), row.get("group")
        _integer(age, "N0 research age label", 20, 70)
        if subject not in groups or groups[subject] != group or row.get("path") in paths:
            raise ValueError("N0 image identity, group or unique path differs.")
        paths.add(_text(row.get("path"), "N0 image metadata path", 1000))
        digest = row.get("sha256")
        if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("N0 image metadata needs a SHA-256; image bytes are not opened.")
        if digest_groups.setdefault(digest, group) != group:
            raise ValueError("N0 exact-byte duplicate crosses identity-use groups.")
        _integer(row.get("bytes"), "N0 image metadata bytes", 1, 1024**3)
        by_subject.setdefault(subject, set()).add(age)
    if set(by_subject) != set(groups):
        raise ValueError("N0 identities and image metadata are incomplete.")
    counts = {"adult_images": len(rows), "adult_identities": len(groups)}
    if counts != {
        "adult_images": _integer(protocol.get("expected_adult_images"), "Expected adult images"),
        "adult_identities": _integer(
            protocol.get("expected_adult_identities"), "Expected identities"
        ),
    }:
        raise ValueError("N0 adult counts differ from the protocol.")
    strata, eligible = {}, {}
    for group in ("all", *sorted(set(groups.values()))):
        selected = rows if group == "all" else [row for row in rows if row["group"] == group]
        strata[group] = {}
        for label in STRATA:
            low, high = (
                int(part) for part in (label.split("-") if "-" in label else [label, label])
            )
            selected_age = [row for row in selected if low <= row["source_age"] <= high]
            strata[group][label] = {
                "images": len(selected_age),
                "identities": len({row["subject_id"] for row in selected_age}),
            }
        eligible[group] = sum(
            len(ages) >= 2
            for subject, ages in by_subject.items()
            if group == "all" or groups[subject] == group
        )
    cases, statuses, seen, known = (
        _list(manifest.get("bridge_cases"), "N0 bridge metadata"),
        Counter(),
        set(),
        0,
    )
    for case in cases:
        sample_id = _text(case.get("sample_id"), "N0 case ID", 100)
        source = case.get("source_age", {})
        age = source.get("value")
        if (
            sample_id in seen
            or case.get("group") != "development"
            or source.get("independently_verified") is not False
            or source.get("method") != ("unknown" if age is None else "dataset_filename")
        ):
            raise ValueError("N0 case use or source-age provenance differs.")
        seen.add(sample_id)
        if age is not None:
            _integer(age, "N0 source research label", 20, 70)
            if case.get("subject_id") not in groups or groups[case["subject_id"]] != "development":
                raise ValueError("N0 known case must belong to a development identity.")
        control = case.get("same_age_control", {})
        status = control.get("status")
        if status not in {
            "blocked_source_failure",
            "not_applicable_unknown_source_age",
            "unsupported_fractional_source_age",
            "pending",
            "reused_existing",
            "generated",
        }:
            raise ValueError("Unsupported N0 same-age control status.")
        if age is None and (
            status not in {"not_applicable_unknown_source_age", "blocked_source_failure"}
            or control.get("target_age") is not None
        ):
            raise ValueError("Unknown N0 source age must remain null and unconditioned.")
        if status in {"generated", "reused_existing"} and control.get("target_age") != age:
            raise ValueError("Same-age control differs from the exact source label.")
        statuses[status] += 1
        known += age is not None and case.get("source_status") == "passed"
    if len(cases) != _integer(
        protocol.get("expected_bridge_samples", 12), "Expected bridge cases"
    ) or known != _integer(protocol.get("expected_known_controls", 8), "Expected controls"):
        raise ValueError("N0 bridge/control counts differ from the protocol.")
    expected = {
        **counts,
        "identity_groups": dict(Counter(groups.values())),
        "image_groups": dict(Counter(row["group"] for row in rows)),
        "control_statuses": dict(sorted(statuses.items())),
        "same_age_controls_complete": known == statuses["generated"] + statuses["reused_existing"],
        "age_strata": strata,
        "distinct_age_pair_eligible_identities": eligible,
    }
    if json.dumps(summary, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ValueError("N0 summary does not match its metadata-only counts and coverage.")
    return expected


def build_report(root: Path, plan_path: Path) -> dict:
    """Verify only bounded metadata and report unresolved preparation dependencies."""
    root = Path(root).resolve(strict=True)
    plan_path = Path(plan_path).resolve(strict=True)
    if not plan_path.is_relative_to(root) or plan_path.suffix != ".json":
        raise ValueError("Study plan must be a workspace JSON metadata file.")
    raw = _read(plan_path)
    plan_pin = {
        "path": plan_path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }
    plan = _json(raw)
    _keys(
        plan,
        {"protocol_id", "catalog", "age_protocol", "n0_manifest", "n0_summary", "source_files"},
        "Study plan",
    )
    if plan["protocol_id"] != PROTOCOL:
        raise ValueError("Unsupported readiness study plan protocol.")
    inputs = _Inputs(root)
    inputs.read(plan_pin)
    roles = ("catalog", "age_protocol", "n0_manifest", "n0_summary")
    primary_paths = [plan[role]["path"] for role in roles]
    if len(set(primary_paths)) != len(primary_paths):
        raise ValueError("Study plan input roles must use distinct paths.")
    values = {role: _json(inputs.read(plan[role])) for role in roles}
    inputs.many(plan["source_files"], "Source files")
    source_pins = {pin["path"]: pin for pin in plan["source_files"]}
    if not set(SOURCE_FILES) <= set(source_pins) or set(primary_paths) & set(source_pins):
        raise ValueError("Source files must separately bind the audit implementation and tests.")
    if source_pins[SOURCE_FILES[0]]["sha256"] != hashlib.sha256(_read(Path(__file__))).hexdigest():
        raise ValueError("Study plan does not pin the running audit implementation.")
    assets = _catalog(values["catalog"], inputs)
    summary = _n0(
        values["age_protocol"], values["n0_manifest"], values["n0_summary"], plan["age_protocol"]
    )
    blockers, asset_reports = [], []
    for asset in assets:
        asset_id, licenses = asset["asset_id"], asset["licenses"]
        if asset["acquisition_state"] == "not_acquired":
            status = "missing"
            blockers.append({"code": "ASSET_NOT_ACQUIRED", "asset_id": asset_id})
        elif any(
            item["status"] in {"missing", "unresolved", "restricted"} for item in licenses.values()
        ):
            status = "unresolved"
        else:
            status = "metadata_available"
        for dimension, item in licenses.items():
            if item["status"] in {"missing", "unresolved", "restricted"}:
                blockers.append(
                    {
                        "code": "USE_TERMS_NOT_CLEARED",
                        "asset_id": asset_id,
                        "dimension": dimension,
                        "status": item["status"],
                    }
                )
        if asset_id.endswith("_evaluator"):
            blockers.append({"code": "EVALUATOR_DOMAIN_VALIDATION_MISSING", "asset_id": asset_id})
            if asset["independence"] != "separate_candidate":
                blockers.append(
                    {
                        "code": "EVALUATOR_INDEPENDENCE_NOT_ESTABLISHED",
                        "asset_id": asset_id,
                        "independence": asset["independence"],
                    }
                )
        asset_reports.append({**asset, "status": status})
    protocol = values["age_protocol"]
    blockers.append({"code": "INDEPENDENT_EVALUATION_NOT_ESTABLISHED"})
    blockers.append({"code": "LEGAL_PERMISSION_NOT_INFERRED_FROM_METADATA"})
    blockers.append(
        {
            "code": "QUALITY_THRESHOLD_NOT_FROZEN"
            if protocol.get("thresholds", {}).get("quality_acceptance") is None
            else "QUALITY_THRESHOLD_NOT_VALIDATED_BY_THIS_AUDIT"
        }
    )
    blockers.append(
        {
            "code": "NEAR_DUPLICATE_REVIEW_NOT_VALIDATED",
            "declared_status": protocol["grouping"].get("near_duplicate_screening"),
        }
    )
    for group in ("calibration_research", "evaluation_research_holdout"):
        for label in STRATA:
            coverage = (
                summary["age_strata"].get(group, {}).get(label, {"images": 0, "identities": 0})
            )
            if not coverage["images"] or not coverage["identities"]:
                blockers.append(
                    {
                        "code": "AGE_STRATUM_MISSING",
                        "group": group,
                        "age_stratum": label,
                        **coverage,
                    }
                )
    inputs.verify()
    return {
        "schema_version": 1,
        "protocol_id": PROTOCOL,
        "reviewed_on": values["catalog"]["reviewed_on"],
        "integrity_status": "passed",
        "preparation_status": "blocked",
        "research_only": True,
        **dict.fromkeys(FALSE_FLAGS, False),
        "legal_permission_established": False,
        "live_artifact_integrity_verified": False,
        "models_loaded": False,
        "images_opened": False,
        "holdout_age_results_opened": False,
        "inputs": [inputs.pins[path] for path in sorted(inputs.pins)],
        "assets": asset_reports,
        "cohort_summary": summary,
        "blockers": blockers,
        "limits": [
            "Pinned metadata is not legal authorization or live weight/image verification.",
            (
                "No model loading, inference, photograph decoding, network access "
                "or holdout age-result reading."
            ),
            "Code, weights, training data and derived distribution terms are assessed separately.",
            (
                "Metadata availability never establishes domain validity, independent quality "
                "or production readiness."
            ),
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--study-plan", type=Path, required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        output = _relative(root, args.output_dir)
        allowed = (root / "output/research").resolve()
        if (
            not output.is_relative_to(allowed)
            or output == allowed
            or not allowed.is_relative_to(root)
        ):
            raise ValueError("Output must be a new descendant of workspace output/research.")
        if output.exists():
            raise FileExistsError("Output directory already exists; prior evidence is preserved.")
        plan = (
            args.study_plan
            if args.study_plan.is_absolute()
            else _relative(root, args.study_plan.as_posix())
        )
        report = build_report(root, plan)
        encoded = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        output.mkdir(parents=True, exist_ok=False)
        with (output / "report.json").open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
        print(
            json.dumps(
                {
                    "integrity_status": "passed",
                    "preparation_status": "blocked",
                    "blockers": len(report["blockers"]),
                }
            )
        )
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as error:
        print(f"{type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

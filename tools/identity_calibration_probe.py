"""Calibrate saved research scores without opening photographs or loading models."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import platform
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from fractions import Fraction
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_ID = "agemorph3d-identity-calibration-v1"
IDENTITY_ID = "agemorph3d-identity-evaluator-v1"
SOURCES = (
    "tools/identity_calibration_probe.py",
    "backend/tests/test_identity_calibration_probe.py",
)
ROLES = (
    "protocol",
    "identity_protocol",
    "identity_study_plan",
    "identity_verification",
    "identity_report",
    "identity_pairs",
    "n0_manifest",
)
GROUPS = ("development", "calibration_research")
PAIR_FIELDS = (
    "pair_id",
    "type",
    "group",
    "category",
    "unit",
    "left_id",
    "right_id",
    "left_status",
    "right_status",
    "status",
    "score",
    "label_age_difference",
)
METRICS = (
    "conditional_fmr",
    "conditional_fnmr",
    "requested_fmr_lower",
    "requested_fmr_upper",
    "requested_fnmr_lower",
    "requested_fnmr_upper",
)
FLAGS = {
    "research_only": True,
    **dict.fromkeys(
        (
            "new_model_inference",
            "calibration_threshold_retuned",
            "independent_evaluation",
            "training_overlap_excluded",
            "legal_permission_established",
            "identity_quality_accepted",
            "age_quality_accepted",
            "service_ready",
            "production_enabled",
            "g3_complete",
        ),
        False,
    ),
}
LIMIT = 2 * 1024**2
MAX_ROWS = 125_000
MAX_RECORDS = 500
IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
with Path(__file__).open("rb") as _source_stream:
    _loaded_bytes = _source_stream.read(LIMIT + 1)
if len(_loaded_bytes) > LIMIT:
    raise ValueError("Loaded CLI exceeds its source byte bound.")
LOADED_CODE_SHA256 = hashlib.sha256(_loaded_bytes).hexdigest()
del _loaded_bytes


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _json(data):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON key.")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("Nonfinite JSON constant.")

    value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict):
        raise ValueError("Metadata must be an object.")
    return value


def _integer(value, minimum=0, maximum=MAX_ROWS):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Invalid bounded integer.")
    return value


def _text(value, maximum=256):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError("Invalid bounded string.")
    return value


def _subject(value):
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise ValueError("Invalid subject identifier.")
    return value


def _list(value, maximum=MAX_RECORDS):
    if (
        not isinstance(value, list)
        or len(value) > maximum
        or any(not isinstance(item, dict) for item in value)
    ):
        raise ValueError("Invalid bounded metadata list.")
    return value


def _pin(value):
    if not isinstance(value, dict) or not {"path", "bytes", "sha256"} <= value.keys():
        raise ValueError("Missing file pin.")
    path = _text(value["path"], 2048)
    if (
        "\\" in path
        or Path(path).is_absolute()
        or path.startswith("/")
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or ":" in path
    ):
        raise ValueError("Pinned path must be workspace relative.")
    size = _integer(value["bytes"], 0, LIMIT)
    digest = value["sha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("Invalid SHA256 pin.")
    return {"path": path, "bytes": size, "sha256": digest}


def _path(root, name):
    path = (root / name).resolve()
    if root not in path.parents:
        raise ValueError("Input escaped the workspace.")
    return path


class Inputs:
    """Exact closed input set; each read/recheck stops at declared length plus one."""

    def __init__(self, root, pins):
        self.root, self.pins = Path(root).resolve(), {}
        for value in _list(pins, len(ROLES) + len(SOURCES)):
            pin = _pin(value)
            _path(self.root, pin["path"])
            if pin["path"] in self.pins:
                raise ValueError("Duplicate frozen input.")
            self.pins[pin["path"]] = pin

    def read(self, value):
        pin = _pin(value)
        if self.pins.get(pin["path"]) != pin:
            raise ValueError("Input missing from exact freeze.")
        with _path(self.root, pin["path"]).open("rb") as stream:
            data = stream.read(pin["bytes"] + 1)
        if len(data) != pin["bytes"] or _hash(data) != pin["sha256"]:
            raise ValueError("Frozen input changed: " + pin["path"])
        return data

    def recheck(self):
        for pin in self.pins.values():
            self.read(pin)


def runtime_fingerprint():
    executable = Path(sys.executable).resolve()
    with executable.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "executable": str(executable),
        "executable_sha256": digest,
    }


def _embed(value):
    if (
        not isinstance(value, list)
        or len(value) != 128
        or any(type(x) not in {int, float} or not math.isfinite(x) for x in value)
        or not any(value)
    ):
        raise ValueError("Invalid saved 128-dimensional feature.")
    scale = max(abs(x) for x in value)
    scaled = [x / scale for x in value]
    norm = math.sqrt(math.fsum(x * x for x in scaled))
    return [x / norm for x in scaled]


def _cosine(left, right):
    return max(-1, min(1, math.fsum(a * b for a, b in zip(left, right, strict=True))))


def _contains_pin(values, pin):
    return pin in [_pin(row) for row in _list(values, 500)]


def _age(value, nullable=False):
    if nullable and value is None:
        return value
    if type(value) not in {int, float} or not math.isfinite(value) or not 20 <= value <= 70:
        raise ValueError("Invalid research age label; unknown must not receive a default.")
    return value


def _closed(report, keys):
    if (
        not isinstance(report, dict)
        or report.get("research_only") is not True
        or any(report.get(k) is not False for k in keys)
    ):
        raise ValueError("Research qualification flags are not closed.")


def validate_metadata(metadata, roles):
    """Validate historical provenance and cohort metadata, not descendant files."""
    protocol = metadata["protocol"]
    if any(
        not isinstance(protocol.get(key), dict)
        for key in ("selection", "evaluation", "uncertainty")
    ):
        raise ValueError("Calibration policy blocks must be objects.")
    if (
        protocol.get("schema_version") != 1
        or protocol.get("protocol_id") != PROTOCOL_ID
        or protocol.get("roles") != list(ROLES)
        or protocol.get("flags") != FLAGS
        or protocol.get("quality_threshold") is not None
        or protocol.get("selection", {}).get("group") != "development"
        or protocol["selection"].get("policy_id") != "macro-discrete-balance-gap-ber-high-v1"
        or protocol.get("evaluation", {}).get("groups") != list(GROUPS)
        or protocol["evaluation"].get("missing_policy_id")
        != "eligible-unit-missing-outcome-bounds-v1"
        or protocol.get("uncertainty", {}).get("replicates") != 1000
        or protocol["uncertainty"].get("seed") != 20261026
        or protocol["uncertainty"].get("policy_id") != "subject-multiplicity-paired-randrange-v1"
        or protocol["uncertainty"].get("metrics") != list(METRICS)
    ):
        raise ValueError("Unsupported calibration protocol or qualification flags.")
    old, plan, verification, report, n0 = (
        metadata[key]
        for key in (
            "identity_protocol",
            "identity_study_plan",
            "identity_verification",
            "identity_report",
            "n0_manifest",
        )
    )
    if (
        n0.get("protocol_id") != "agemorph3d-age-research-v1"
        or n0.get("research_only") is not True
        or n0.get("training_use") is not False
        or n0.get("service_ready") is not False
        or n0.get("g3_complete") is not False
    ):
        raise ValueError("N0 source split is not the closed historical research manifest.")
    historical_flags = (
        "identity_quality_accepted",
        "independent_evaluation",
        "training_overlap_excluded",
        "legal_permission_established",
        "service_ready",
        "production_enabled",
        "g3_complete",
    )
    _closed(old.get("flags", {}), historical_flags)
    _closed(report, historical_flags)
    for value in (old, report):
        if value.get("protocol_id") != IDENTITY_ID or value.get("quality_threshold") is not None:
            raise ValueError("Historical identity protocol/report differs.")
    if (
        plan.get("protocol_id") != IDENTITY_ID
        or plan.get("protocol") != roles["identity_protocol"]
        or plan.get("n0_manifest") != roles["n0_manifest"]
        or report.get("integrity_status") != "passed"
        or report.get("models_closed") is not True
        or report.get("holdout_embeddings_extracted") is not False
        or report.get("images_or_crops_written") is not False
        or report.get("pairs_csv") != roles["identity_pairs"]
    ):
        raise ValueError("Historical plan/report crosslink or completion differs.")
    for role in ("identity_study_plan", "identity_protocol", "n0_manifest"):
        if not _contains_pin(report.get("inputs"), roles[role]):
            raise ValueError("Historical report omits the selected plan or metadata.")
    for role in ("identity_study_plan", "identity_report", "identity_pairs"):
        if not _contains_pin(verification.get("evidence"), roles[role]):
            raise ValueError("Historical final verification does not bind selected evidence.")
    cohorts = old.get("cohort")
    if not isinstance(cohorts, dict) or cohorts.get("groups") != list(GROUPS):
        raise ValueError("Unsupported original identity cohort.")
    for key in (
        "expected_originals",
        "expected_generated",
        "expected_sources",
        "expected_unique_images",
        "expected_original_pairs",
        "expected_source_generated_pairs",
    ):
        _integer(cohorts.get(key), 0, MAX_ROWS)
    subjects = {}
    for item in _list(n0.get("identities")):
        subject = _subject(item.get("subject_id"))
        group = item.get("group")
        if subject in subjects or group not in {*GROUPS, "evaluation_research_holdout"}:
            raise ValueError("Duplicate subject or invalid immutable identity split.")
        subjects[subject] = group
    eligible, held_paths, held_hashes, all_paths, hash_groups = {}, set(), set(), set(), {}
    for item in _list(n0.get("adult_images")):
        pin, subject = _pin(item), _subject(item.get("subject_id"))
        group = item.get("group")
        if group != subjects.get(subject) or pin["path"] in all_paths:
            raise ValueError("N0 image group/subject split or uniqueness differs.")
        all_paths.add(pin["path"])
        label = _age(item.get("source_age"))
        if group == "evaluation_research_holdout":
            held_paths.add(pin["path"])
            held_hashes.add(pin["sha256"])
        else:
            if pin["sha256"] in hash_groups and hash_groups[pin["sha256"]] != group:
                raise ValueError("An exact original image crosses development/calibration groups.")
            hash_groups[pin["sha256"]] = group
            eligible[pin["path"]] = (pin, subject, group, label)
    records, originals, seen_paths, normalized = {}, {}, set(), {}
    for record in _list(report.get("records")):
        image_id = _integer(record.get("image_id"), 0, MAX_RECORDS - 1)
        pin = _pin(record.get("source"))
        group, roleset = record.get("group"), record.get("roles")
        if (
            image_id in records
            or pin["path"] in seen_paths
            or group not in GROUPS
            or not isinstance(roleset, list)
            or not roleset
            or len(roleset) > 2
            or len(set(roleset)) != len(roleset)
            or any(x not in {"original", "source", "generated"} for x in roleset)
            or "generated" in roleset
            and len(roleset) != 1
            or pin["path"] in held_paths
            or pin["sha256"] in held_hashes
        ):
            raise ValueError("Saved image identity, roles, split or held-out exclusion differs.")
        subject = record.get("subject_id")
        if (
            "original" not in roleset
            and isinstance(subject, str)
            and subject.startswith("external:")
        ):
            # These historical bookkeeping IDs never enter original trials or units.
            _subject(subject.removeprefix("external:"))
        else:
            _subject(subject)
        seen_paths.add(pin["path"])
        status = _text(record.get("status"), 64)
        label = _age(record.get("source_age_label"), nullable=True)
        if "original" in roleset:
            if eligible.get(pin["path"]) != (pin, subject, group, label):
                raise ValueError("Original image record is not exactly its N0 member.")
            originals[image_id] = record
            if status == "ok":
                normalized[image_id] = _embed(record.get("embedding"))
            elif record.get("embedding") is not None:
                raise ValueError("A failed original still carries a feature.")
        elif pin["path"] in eligible:
            raise ValueError("Original role was removed from a selected N0 member.")
        records[image_id] = record
    if (
        len(originals) != len(eligible)
        or {r["source"]["path"] for r in originals.values()} != set(eligible)
        or set(records) != set(range(len(records)))
        or len(records) != cohorts["expected_unique_images"]
        or len(originals) != cohorts["expected_originals"]
        or sum("generated" in r["roles"] for r in records.values()) != cohorts["expected_generated"]
        or sum("source" in r["roles"] for r in records.values()) != cohorts["expected_sources"]
    ):
        raise ValueError("Historical complete image cohort differs.")
    image_counts = report.get("image_counts", {})
    successful = sum(r["status"] == "ok" for r in records.values())
    if (
        image_counts.get("requested") != len(records)
        or image_counts.get("successful") != successful
        or image_counts.get("failed") != len(records) - successful
    ):
        raise ValueError("Historical image totals disagree with saved records.")
    return records, originals, normalized, cohorts


def parse_trials(data, metadata, roles):
    records, originals, normalized, cohorts = validate_metadata(metadata, roles)
    if not isinstance(data, bytes) or len(data) > LIMIT:
        raise ValueError("CSV byte budget exceeded.")
    stream = io.StringIO(data.decode("utf-8"), newline="")
    reader = csv.reader(stream, strict=True)
    if next(reader, None) != list(PAIR_FIELDS):
        raise ValueError("CSV header differs from the original exact schema.")
    expected = {}
    subjects = {
        group: sorted({r["subject_id"] for r in originals.values() if r["group"] == group})
        for group in GROUPS
    }
    for group in GROUPS:
        members = [i for i, record in originals.items() if record["group"] == group]
        for left, right in combinations(members, 2):
            a, b = originals[left], originals[right]
            same, same_age = (
                a["subject_id"] == b["subject_id"],
                a["source_age_label"] == b["source_age_label"],
            )
            category = ("same_identity" if same else "different_identity") + (
                "_same_age" if same_age else "_cross_age"
            )
            unit = a["subject_id"] if same else ":".join(sorted((a["subject_id"], b["subject_id"])))
            expected[frozenset((left, right))] = {
                "group": group,
                "category": category,
                "unit": unit,
                "difference": abs(a["source_age_label"] - b["source_age_label"]),
            }
    if len(expected) != cohorts["expected_original_pairs"]:
        raise ValueError("Original pair request count differs from its protocol.")
    trials, pair_ids, seen_original, seen_generated, excluded = [], set(), set(), set(), 0
    all_failed, excluded_failed = 0, 0
    for cells in reader:
        if (
            len(pair_ids) >= MAX_ROWS
            or len(cells) != len(PAIR_FIELDS)
            or any(len(x) > 256 for x in cells)
        ):
            raise ValueError("CSV row/field budget or column count differs.")
        row = dict(zip(PAIR_FIELDS, cells, strict=True))
        numbers = []
        for key in ("pair_id", "left_id", "right_id"):
            if re.fullmatch(r"0|[1-9][0-9]*", row[key]) is None:
                raise ValueError("CSV identifiers must be canonical nonnegative integers.")
            numbers.append(_integer(int(row[key])))
        pair_id, left, right = numbers
        if pair_id in pair_ids or left == right or left not in records or right not in records:
            raise ValueError("CSV duplicated or dangling pair identifier.")
        pair_ids.add(pair_id)
        a, b = records[left], records[right]
        if row["left_status"] != a["status"] or row["right_status"] != b["status"]:
            raise ValueError("CSV status is not bound to its saved image records.")
        scored = a["status"] == b["status"] == "ok"
        all_failed += not scored
        if row["status"] != ("scored" if scored else "failed"):
            raise ValueError("CSV pair status differs from saved source availability.")
        score = None
        if scored:
            try:
                score = float(row["score"])
            except ValueError as error:
                raise ValueError("Invalid numeric CSV score.") from error
            if not math.isfinite(score) or not -1 <= score <= 1:
                raise ValueError("CSV score must be a finite cosine in [-1,1].")
        elif row["score"] != "":
            raise ValueError("Failed comparisons require an absent score, never zero.")
        key = frozenset((left, right))
        if row["type"] == "original_comparison":
            if key not in expected or key in seen_original:
                raise ValueError(
                    "CSV original pair missing, duplicated, cross-group or reassigned."
                )
            seen_original.add(key)
            value = expected[key]
            if any(row[k] != value[k] for k in ("group", "category", "unit")) or row[
                "label_age_difference"
            ] != str(value["difference"]):
                raise ValueError("CSV original labels do not match saved N0 identities/ages.")
            if (
                score is not None
                and abs(score - _cosine(normalized[left], normalized[right])) > 1e-12
            ):
                raise ValueError("CSV score differs from its saved original feature numbers.")
            trials.append(
                {
                    "group": value["group"],
                    "category": value["category"],
                    "unit": value["unit"],
                    "subjects": sorted({a["subject_id"], b["subject_id"]}),
                    "score": score,
                }
            )
        elif row["type"] == "source_generated_comparison":
            if (
                "source" not in a["roles"]
                or b["roles"] != ["generated"]
                or row["group"] != "development"
                or a["group"] != b["group"]
                or a["subject_id"] != b["subject_id"]
                or right in seen_generated
                or a["source_age_label"] != b["source_age_label"]
                or row["unit"] != b.get("source_id")
            ):
                raise ValueError("CSV generated exclusion was reassigned or overlaps originals.")
            seen_generated.add(right)
            target = _age(b.get("target_condition"))
            source_age = a["source_age_label"]
            category = (
                "unknown_source_age"
                if source_age is None
                else "same_age_control"
                if source_age == target
                else "other_condition"
            )
            difference = "" if source_age is None else str(abs(source_age - target))
            if row["category"] != category or row["label_age_difference"] != difference:
                raise ValueError(
                    "Generated row labels differ; generated scores are not training labels."
                )
            excluded += 1
            excluded_failed += not scored
        else:
            raise ValueError("Unknown CSV comparison type.")
    if (
        seen_original != set(expected)
        or pair_ids != set(range(len(pair_ids)))
        or excluded != cohorts["expected_source_generated_pairs"]
        or len(seen_generated) != cohorts["expected_generated"]
    ):
        raise ValueError("CSV does not contain the complete historical request set.")
    counts = metadata["identity_report"].get("pair_counts", {})
    failed = sum(t["score"] is None for t in trials)
    if (
        counts.get("requested") != len(pair_ids)
        or counts.get("failed") != all_failed
        or counts.get("scored") != len(pair_ids) - all_failed
    ):
        raise ValueError("Historical pair totals disagree with the complete saved CSV.")
    return (
        trials,
        subjects,
        {
            "requested_csv_pairs": len(pair_ids),
            "original_pairs": len(trials),
            "excluded_generated_pairs": excluded,
            "excluded_generated_failed": excluded_failed,
            "same_identity_same_age_pairs": sum(
                t["category"] == "same_identity_same_age" for t in trials
            ),
            "failed_original_pairs": failed,
        },
    )


def units_for(trials, category):
    units = defaultdict(list)
    for trial in trials:
        selected = (
            trial["category"] == category
            if category != "negative"
            else trial["category"].startswith("different_identity_")
        )
        if selected:
            units[trial["unit"]].append(trial)
    return dict(units)


def development_curve(trials):
    """Exact rational event scan; calibration scores cannot create candidates or ties."""
    development = [t for t in trials if t["group"] == "development"]
    classes = [units_for(development, name) for name in ("same_identity_cross_age", "negative")]
    events = defaultdict(lambda: [Fraction(0), Fraction(0)])
    for kind, units in enumerate(classes):
        effective = [rows for rows in units.values() if any(r["score"] is not None for r in rows)]
        if not effective:
            raise ValueError("Both development classes need at least one effective scored unit.")
        for rows in effective:
            scores = [r["score"] for r in rows if r["score"] is not None]
            weight = Fraction(1, len(effective) * len(scores))
            for score in scores:
                if (
                    type(score) not in {int, float}
                    or not math.isfinite(score)
                    or not -1 <= score <= 1
                ):
                    raise ValueError("Invalid development score.")
                events[score][kind] += weight
    if len(events) > MAX_ROWS:
        raise ValueError("Development curve exceeds candidate budget.")
    accepted = [Fraction(0), Fraction(0)]
    curve, keys = [], []

    def append(threshold, kind):
        fmr, fnmr = accepted[1], 1 - accepted[0]
        gap, balanced = abs(fmr - fnmr), (fmr + fnmr) / 2
        curve.append(
            {
                "threshold": threshold,
                "kind": kind,
                "conditional_fmr": float(fmr),
                "conditional_fnmr": float(fnmr),
                "balanced_error": float(balanced),
                "absolute_error_gap": float(gap),
            }
        )
        keys.append((gap, balanced, -threshold))

    append(math.nextafter(max(events), math.inf), "above_development_max")
    for score in sorted(events, reverse=True):
        accepted = [a + b for a, b in zip(accepted, events[score], strict=True)]
        append(score, "development_score")
    index = min(range(len(curve)), key=keys.__getitem__)
    return curve, {
        **curve[index],
        "curve_index": index,
        "selection_key_exact": [[v.numerator, v.denominator] for v in keys[index][:2]],
    }


def unit_metrics(trials, category, threshold):
    units = units_for(trials, category)
    negative = category == "negative"
    result = []
    for key, rows in sorted(units.items()):
        scores = [r["score"] for r in rows if r["score"] is not None]
        errors = sum((s >= threshold) if negative else (s < threshold) for s in scores)
        requested, scored = len(rows), len(scores)
        result.append(
            {
                "unit": key,
                "subjects": rows[0]["subjects"],
                "requested": requested,
                "scored": scored,
                "failed": requested - scored,
                "false_decisions": errors,
                "conditional_error_rate": errors / scored if scored else None,
                "requested_error_lower": errors / requested,
                "requested_error_upper": (errors + requested - scored) / requested,
            }
        )
    return result


def weighted_metrics(units, multiplicities=None):
    """One subject draw weights errors and unknown-outcome bounds consistently."""
    conditional, lower, upper, effective, eligible = Fraction(0), Fraction(0), Fraction(0), 0, 0
    for unit in units:
        weight = 1
        if multiplicities is not None:
            for subject in unit["subjects"]:
                weight *= multiplicities.get(subject, 0)
        if weight == 0:
            continue
        eligible += weight
        requested, scored, errors, failed = (
            unit[k] for k in ("requested", "scored", "false_decisions", "failed")
        )
        lower += weight * Fraction(errors, requested)
        upper += weight * Fraction(errors + failed, requested)
        if scored:
            effective += weight
            conditional += weight * Fraction(errors, scored)
    return {
        "conditional_error_rate": float(conditional / effective) if effective else None,
        "requested_error_lower": float(lower / eligible) if eligible else None,
        "requested_error_upper": float(upper / eligible) if eligible else None,
        "eligible_units": eligible,
        "effective_units": effective,
    }


def class_summary(units):
    return {
        **weighted_metrics(units),
        **{
            name: sum(u[name] for u in units)
            for name in ("requested", "scored", "failed", "false_decisions")
        },
        "units": units,
    }


def percentile(values, probability):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lo, hi = math.floor(position), math.ceil(position)
    return ordered[lo] + (position - lo) * (ordered[hi] - ordered[lo])


def bootstrap(positive, negative, subjects, seed, replicates=1000):
    if subjects != sorted(set(subjects)) or not subjects or len(subjects) > MAX_RECORDS:
        raise ValueError("Bootstrap subject universe must be sorted, unique and nonempty.")
    _integer(replicates, 1, 1000)
    rng = random.Random(seed)
    values = {name: [] for name in METRICS}
    for _ in range(replicates):
        counts = Counter(subjects[rng.randrange(len(subjects))] for _ in subjects)
        p, n = weighted_metrics(positive, counts), weighted_metrics(negative, counts)
        samples = (
            n["conditional_error_rate"],
            p["conditional_error_rate"],
            n["requested_error_lower"],
            n["requested_error_upper"],
            p["requested_error_lower"],
            p["requested_error_upper"],
        )
        for name, value in zip(METRICS, samples, strict=True):
            values[name].append(value)
    answer = {}
    for name, samples in values.items():
        finite = [x for x in samples if x is not None]
        encoded = json.dumps(samples, separators=(",", ":"), allow_nan=False).encode()
        answer[name] = {
            "valid_replicates": len(finite),
            "null_replicates": replicates - len(finite),
            "percentile_025": percentile(finite, 0.025),
            "percentile_975": percentile(finite, 0.975),
            "replicate_values_sha256": _hash(encoded),
        }
    return {
        "replicates": replicates,
        "seed": seed,
        "subjects": subjects,
        "fixed_threshold_reselected": False,
        "metrics": answer,
    }


def calibrate(trials, subjects, replicates=1000, seed=20261026):
    curve, selected = development_curve(trials)
    threshold, groups = selected["threshold"], {}
    for index, group in enumerate(GROUPS):
        own = [r for r in trials if r["group"] == group]
        positive = unit_metrics(own, "same_identity_cross_age", threshold)
        negative = unit_metrics(own, "negative", threshold)
        groups[group] = {
            "fixed_threshold": threshold,
            "positive_cross_age": class_summary(positive),
            "negative_all_ages": class_summary(negative),
            "same_identity_same_age": class_summary(
                unit_metrics(own, "same_identity_same_age", threshold)
            ),
            "bootstrap": bootstrap(positive, negative, subjects[group], seed + index, replicates),
        }
    return {
        "development_curve": curve,
        "development_candidate_threshold": threshold,
        "development_selection": selected,
        "groups": groups,
        "calibration_curve_computed": False,
        "quality_threshold": None,
    }


def _output(root, name):
    path = Path(name)
    path = (path if path.is_absolute() else root / path).resolve()
    research = (root / "output/research").resolve()
    if root not in research.parents or research not in path.parents or path.exists():
        raise ValueError("Output must be a fresh directory inside ignored output/research.")
    return path


def run(args):
    root = Path(args.root).resolve()
    output = _output(root, args.output_dir)
    plan_path = Path(args.study_plan)
    plan_path = (plan_path if plan_path.is_absolute() else root / plan_path).resolve()
    if root not in plan_path.parents:
        raise ValueError("Study plan escaped the workspace.")
    with plan_path.open("rb") as stream:
        plan_bytes = stream.read(LIMIT + 1)
    if len(plan_bytes) > LIMIT:
        raise ValueError("Study plan exceeds metadata budget.")
    plan = _json(plan_bytes)
    runtime = runtime_fingerprint()
    if (
        plan.get("schema_version") != 1
        or plan.get("protocol_id") != PROTOCOL_ID
        or plan.get("runtime") != runtime
        or set(plan.get("roles", {})) != set(ROLES)
    ):
        raise ValueError("Frozen protocol roles or Python runtime differ.")
    roles = {key: _pin(value) for key, value in plan["roles"].items()}
    inputs = Inputs(root, plan.get("inputs"))
    required = {pin["path"] for pin in roles.values()} | set(SOURCES)
    if set(inputs.pins) != required or len(required) != len(ROLES) + len(SOURCES):
        raise ValueError("Freeze is not the exact seven-role and implementation input set.")
    for source in SOURCES:
        inputs.read(inputs.pins[source])
    if inputs.pins[SOURCES[0]]["sha256"] != LOADED_CODE_SHA256:
        raise ValueError("Loaded CLI differs from the newly pinned file on disk.")
    metadata = {
        key: _json(inputs.read(pin)) for key, pin in roles.items() if key != "identity_pairs"
    }
    trials, subjects, accounting = parse_trials(
        inputs.read(roles["identity_pairs"]), metadata, roles
    )
    result = calibrate(trials, subjects)

    def recheck():
        inputs.recheck()
        with plan_path.open("rb") as stream:
            current = stream.read(len(plan_bytes) + 1)
        if current != plan_bytes or runtime_fingerprint() != runtime:
            raise ValueError("Plan or runtime drift after calculation.")

    recheck()
    report = {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        **FLAGS,
        "study_plan": {
            "path": plan_path.relative_to(root).as_posix(),
            "bytes": len(plan_bytes),
            "sha256": _hash(plan_bytes),
        },
        "roles": roles,
        "inputs": list(inputs.pins.values()),
        "runtime": runtime,
        "input_accounting": accounting,
        **result,
        "integrity": {
            "all_inputs_unchanged": True,
            "plan_unchanged": True,
            "runtime_unchanged": True,
        },
        "limitations": metadata["protocol"]["observations"],
        "bootstrap_scope": metadata["protocol"]["uncertainty"]["limitations"],
    }
    data = (json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    if len(data) > 8 * LIMIT:
        raise ValueError("Bounded report budget exceeded.")
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
                {
                    "development_candidate_threshold": report["development_candidate_threshold"],
                    "curve_points": len(report["development_curve"]),
                    "input_accounting": report["input_accounting"],
                }
            )
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError, csv.Error, RecursionError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

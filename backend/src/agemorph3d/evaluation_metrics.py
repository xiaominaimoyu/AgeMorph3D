"""Frozen-ledger scalar comparisons and explicit 2D NME; no benchmark acceptance."""

from __future__ import annotations

import copy
import itertools
import math
from collections import Counter

from .age_statistics import aggregate_identity_metrics

PROTOCOL = "agemorph3d-paired-metrics-v1"
MAX_REQUESTS = 10_000
MAX_VARIANTS = 8
MAX_STRATA = 32
MAX_BOOTSTRAP_WORK = 10_000_000
FLAGS = dict.fromkeys(
    (
        "formal_evaluation_completed",
        "independent_evaluation",
        "quality_accepted",
        "service_ready",
        "production_enabled",
        "g3_complete",
    ),
    False,
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _keys(value, names):
    _require(type(value) is dict and set(value) == set(names), "Unexpected or missing fields.")


def _text(value):
    _require(
        type(value) is str and 0 < len(value.strip()) <= 200 and all(ord(c) >= 32 for c in value),
        "Invalid bounded identifier/description.",
    )
    return value


def _number(value):
    _require(type(value) in (int, float), "Metric must be finite and not boolean.")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError("Metric exceeds finite floating-point range.") from error
    _require(math.isfinite(number), "Metric must be finite and not boolean.")
    return number


def nme_2d(predicted, reference, visible, normalizer):
    """Compute a ratio only for explicitly corresponding visible 2D points.

    Invisible points may be null, never imputed. Their supplied coordinates, if
    present, must still be finite. Point semantics and normalizer are caller
    declarations, not verification of a particular benchmark or ground truth.
    """
    for packet in (predicted, reference):
        _keys(packet, ("point_ids", "points", "coordinate_frame"))
        _text(packet["coordinate_frame"])
        ids, points = packet["point_ids"], packet["points"]
        _require(
            type(ids) is list and type(points) is list and 1 <= len(ids) == len(points) <= 1000,
            "Bound corresponding landmark IDs and coordinates.",
        )
        for key in ids:
            _text(key)
        _require(len(set(ids)) == len(ids), "Landmark IDs must be unique.")
    _require(
        predicted["point_ids"] == reference["point_ids"]
        and predicted["coordinate_frame"] == reference["coordinate_frame"],
        "Landmark semantic order or coordinate frame differs.",
    )
    _require(
        type(visible) is list
        and len(visible) == len(predicted["points"])
        and all(type(v) is bool for v in visible)
        and any(visible),
        "Require explicit nonempty visible-point selection.",
    )
    _keys(normalizer, ("id", "distance"))
    _text(normalizer["id"])
    distance = _number(normalizer["distance"])
    _require(distance > 0, "Normalization distance must be positive.")
    errors = []
    for left, right, used in zip(predicted["points"], reference["points"], visible, strict=True):
        for point in (left, right):
            if point is None:
                _require(not used, "Visible landmarks cannot be missing.")
            else:
                _require(type(point) is list and len(point) == 2, "Expected a 2D landmark.")
                for coordinate in point:
                    _number(coordinate)
        if used:
            errors.append(math.dist(left, right) / distance)
    ratio = _number(math.fsum(e / len(errors) for e in errors))
    return {
        "ratio": ratio,
        "visible_points": len(errors),
        "requested_points": len(visible),
        "point_ids": list(predicted["point_ids"]),
        "coordinate_frame": predicted["coordinate_frame"],
        "normalizer": copy.deepcopy(normalizer),
        "benchmark_equivalence_verified": False,
    }


def summarize_study(packet):
    """Reuse identity statistics after enforcing a complete immutable request set."""
    _keys(
        packet,
        (
            "schema_version",
            "protocol_id",
            "research_only",
            "metric",
            "bootstrap",
            "requests",
            "variants",
            "provenance",
        ),
    )
    _require(
        type(packet["schema_version"]) is int
        and packet["schema_version"] == 1
        and packet["protocol_id"] == PROTOCOL
        and packet["research_only"] is True,
        "Unsupported research metric packet.",
    )
    metric = packet["metric"]
    _keys(metric, ("id", "unit", "direction", "normalization", "quality_threshold"))
    for key in ("id", "unit", "normalization"):
        _text(metric[key])
    _require(
        metric["direction"] in ("lower", "higher") and metric["quality_threshold"] is None,
        "Declare direction and retain an unestablished quality threshold.",
    )
    config = packet["bootstrap"]
    _keys(config, ("seed", "samples"))
    _require(
        type(config["seed"]) is int
        and 0 <= config["seed"] <= 2**32 - 1
        and type(config["samples"]) is int
        and 1 <= config["samples"] <= 10_000,
        "Bootstrap needs bounded explicit integer seed/sample count.",
    )
    ledger, variants = packet["requests"], packet["variants"]
    _require(
        type(ledger) is list and 1 <= len(ledger) <= MAX_REQUESTS, "Invalid request ledger count."
    )
    _require(
        type(variants) is list and 1 <= len(variants) <= MAX_VARIANTS, "Invalid variant count."
    )
    lookup = {}
    for request in ledger:
        _keys(request, ("request_id", "subject_id", "stratum"))
        for value in request.values():
            _text(value)
        key = request["request_id"]
        _require(key not in lookup, "Duplicate frozen request ID.")
        lookup[key] = request
    subjects = sorted({r["subject_id"] for r in ledger})
    strata = sorted({r["stratum"] for r in ledger})
    _require(len(strata) <= MAX_STRATA, "Too many strata.")
    work = (
        config["samples"]
        * len(subjects)
        * (len(strata) + 1)
        * (len(variants) + len(variants) * (len(variants) - 1) // 2)
    )
    _require(work <= MAX_BOOTSTRAP_WORK, "Bootstrap work budget exceeded.")
    provenance = packet["provenance"]
    _require(type(provenance) is list and len(provenance) <= 32, "Bound declared provenance pins.")
    seen_paths = set()
    for pin in provenance:
        _keys(pin, ("path", "bytes", "sha256"))
        name = _text(pin["path"])
        _require(
            name not in seen_paths
            and not name.startswith("/")
            and "\\" not in name
            and ":" not in name
            and all(p not in {"", ".", ".."} for p in name.split("/")),
            "Invalid/duplicate declared provenance path.",
        )
        seen_paths.add(name)
        _require(
            type(pin["bytes"]) is int
            and pin["bytes"] > 0
            and type(pin["sha256"]) is str
            and len(pin["sha256"]) == 64
            and all(c in "0123456789abcdef" for c in pin["sha256"]),
            "Invalid provenance size/hash.",
        )
    values = {}
    for variant in variants:
        _keys(variant, ("name", "records"))
        name = _text(variant["name"])
        _require(name not in values, "Duplicate variant name.")
        rows = variant["records"]
        _require(
            type(rows) is list and len(rows) == len(ledger),
            "Every frozen request needs an explicit result.",
        )
        results = {}
        for row in rows:
            _keys(row, ("request_id", "status", "value", "error_code"))
            key = _text(row["request_id"])
            _require(key in lookup and key not in results, "Unknown/duplicate result request ID.")
            if row["status"] == "ok":
                _number(row["value"])
                _require(
                    row["error_code"] is None, "Successful metrics cannot carry failure codes."
                )
            else:
                _require(
                    row["status"] == "failed" and row["value"] is None,
                    "Failed results retain null metrics, not zero/imputed values.",
                )
                _text(row["error_code"])
            results[key] = row
        _require(set(results) == set(lookup), "Result ledger differs from frozen requests.")
        values[name] = results

    def aggregate(rows):
        summary = aggregate_identity_metrics(
            rows, ["value"], bootstrap_seed=config["seed"], bootstrap_samples=config["samples"]
        )
        summary["requested_identities"] = len({r["subject_id"] for r in rows})
        summary["identities_without_valid_metrics"] = sorted(
            s for s, row in summary["per_identity"].items() if row["metrics"]["value"]["count"] == 0
        )
        return summary

    reports = {}
    for name, results in values.items():
        records = [
            dict(lookup[key], **{k: row[k] for k in ("status", "value", "error_code")})
            for key, row in sorted(results.items())
        ]
        reports[name] = {
            "summary": aggregate(records),
            "strata": {s: aggregate([r for r in records if r["stratum"] == s]) for s in strata},
            "failure_codes": dict(
                Counter(r["error_code"] for r in records if r["status"] == "failed")
            ),
            "records": records,
        }
    comparisons = []
    for left_name, right_name in itertools.combinations(values, 2):
        categories = {
            "common_success": [],
            "left_only_success": [],
            "right_only_success": [],
            "both_failed": [],
        }
        deltas = []
        for key in sorted(lookup):
            left, right = values[left_name][key], values[right_name][key]
            a, b = left["status"] == "ok", right["status"] == "ok"
            kind = (
                "common_success"
                if a and b
                else "left_only_success"
                if a
                else "right_only_success"
                if b
                else "both_failed"
            )
            categories[kind].append(key)
            if a and b:
                delta = _number(right["value"] - left["value"])
                deltas.append(dict(lookup[key], status="ok", value=delta))
        comparisons.append(
            {
                "left": left_name,
                "right": right_name,
                "delta_definition": "right_minus_left",
                "all_requested_pairs": len(ledger),
                "request_sets": categories,
                "paired_summary": aggregate(deltas),
                "strata": {s: aggregate([r for r in deltas if r["stratum"] == s]) for s in strata},
                "requested_identities": len(subjects),
                "identities_without_common_success": sorted(
                    set(subjects) - {r["subject_id"] for r in deltas}
                ),
            }
        )
    return {
        "protocol_id": PROTOCOL,
        "status": "completed_with_failures"
        if any(r["status"] == "failed" for rows in values.values() for r in rows.values())
        else "completed",
        "metric": copy.deepcopy(metric),
        "bootstrap": copy.deepcopy(config),
        "requests": copy.deepcopy(ledger),
        "requested_pairs": len(ledger),
        "requested_identities": len(subjects),
        "variants": reports,
        "comparisons": comparisons,
        "provenance": copy.deepcopy(provenance),
        "provenance_files_verified": False,
        "model_inference_run": False,
        "quality_threshold": None,
        "research_only": True,
        **FLAGS,
    }

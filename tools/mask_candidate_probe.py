"""Bounded JSON-only sensitivity to removing the historical candidate band.

The upper bound deliberately permits uncertain generated pixels. It is not a
usable mask, external-occlusion truth, NO_FACE cause, or quality acceptance.
Original images, masks, correspondence vectors and geometry are never written.
"""

# Offline entrypoint sharing the existing frozen byte and numeric validators.
# ruff: noqa: E402
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "tools"))

import cv2
import mask_replay_probe as mask
import mask_review_workbench as workbench
import numpy as np

uv = mask.uv
PROTOCOL_ID = "agemorph3d-mask-candidate-v1"
ROLES = ("protocol", "mask_report", "mask_audit", "uv_report")
SOURCES = (
    *mask.SOURCES,
    "tools/mask_review_workbench.py",
    "tools/mask_candidate_probe.py",
    "backend/tests/test_mask_candidate_probe.py",
)
FALSE_FLAGS = (*workbench.FALSE_FLAGS, "usable_mask_candidate_accepted")
ARMS = ("old_baseline", "remove_B_upper_bound")
_LOADED_SOURCE_HASHES = {
    name: uv._digest((_ROOT / name).read_bytes())
    for name in SOURCES
    if name.endswith(".py") and "/tests/" not in name
}


def derive_input_pins(metadata):
    return workbench.derive_input_pins(metadata)


def _protocol(protocol):
    if (
        protocol.get("schema_version") != 1
        or protocol.get("protocol_id") != PROTOCOL_ID
        or protocol["cohort"]["sources"] != uv.COHORT
        or protocol["cohort"]["expected_targets"] != 12
        or protocol["cohort"]["group"] != "development"
        or protocol["cohort"]["api_source_age"] != uv.UNKNOWN_AGE
        or protocol["quality_threshold"] is not None
        or protocol["flags"] != {"research_only": True, **dict.fromkeys(FALSE_FLAGS, False)}
        or protocol["arms"] != list(ARMS)
        or {key: value for key, value in protocol["counterfactual"].items() if key != "description"}
        != {
            "allowed": "E & ~M",
            "occluded": "none",
            "only_transition": [5, 6],
            "upper_bound_only": True,
        }
        or protocol["observations"]["historical_mask_results_seen_before_freeze"] is not True
        or protocol["observations"]["candidate_results_seen_before_freeze"] is not False
    ):
        raise ValueError("Unsupported sensitivity protocol, arms or closed research boundary.")


def _candidate_arrays(candidate):
    names = ("H", "E", "M", "B", "base", "allowed", "occluded")
    if not isinstance(candidate, dict) or set(candidate) != {*names, "reason", "pixel_counts"}:
        raise ValueError("The complete historical mask construction is required.")
    if any(not isinstance(candidate[name], np.ndarray) for name in (*names, "reason")):
        raise ValueError("Candidate layers must be explicit bounded arrays.")
    allowed, occluded = candidate["allowed"], candidate["occluded"]
    uv._masks(allowed, occluded)
    if any(
        candidate[name].dtype != np.bool_ or candidate[name].shape != allowed.shape
        for name in names
    ):
        raise ValueError("All historical construction layers must share the boolean pixel frame.")
    h, e, m, band, base = (candidate[name] for name in ("H", "E", "M", "B", "base"))
    if (
        np.any(e & ~h)
        or not np.array_equal(base, e & ~m)
        or not np.array_equal(allowed, base & ~band)
        or not np.array_equal(occluded, base & band)
        or not np.array_equal(base, allowed | occluded)
    ):
        raise ValueError("Candidate base, old allowed or old band masks disagree.")
    reason = np.zeros(allowed.shape, np.uint8)
    reason[~h] = 1
    reason[h & ~e] = 2
    reason[e & m] = 3
    reason[occluded] = 4
    if (
        candidate["reason"].dtype != np.uint8
        or not np.array_equal(reason, candidate["reason"])
        or not isinstance(candidate["pixel_counts"], dict)
        or candidate["pixel_counts"]
        != {
            **{name: int(candidate[name].sum()) for name in names},
            "reasons": {
                name: int(np.count_nonzero(reason == code))
                for name, code in mask.PIXEL_REASONS.items()
            },
        }
    ):
        raise ValueError("Candidate recipe reasons or layer pixel counts disagree.")
    return allowed, occluded, base


def _vector_arrays(vectors, classification):
    if not isinstance(vectors, dict) or set(vectors) != set(mask.VECTOR_NAMES):
        raise ValueError("Exactly the seven saved correspondence arrays are required.")
    if not isinstance(vectors["face_owner"], np.ndarray) or vectors["face_owner"].ndim != 1:
        raise ValueError("Saved owners must be a one-dimensional array.")
    count = len(vectors["face_owner"])
    if not 0 <= count <= 65536:
        raise ValueError("Saved correspondence count exceeds the atlas.")
    for name in mask.VECTOR_NAMES:
        columns = (
            2
            if name == "texel_rows_columns"
            else 3
            if name in {"barycentric", "target_xyz", "source_canonical_xyz"}
            else None
        )
        shape = (count, columns) if columns else (count,)
        array = vectors[name]
        if (
            not isinstance(array, np.ndarray)
            or array.shape != shape
            or array.dtype != mask.VECTOR_DTYPES[name]
            or array.dtype.kind == "f"
            and not np.isfinite(array).all()
        ):
            raise ValueError("Saved vector shape, dtype or finite values differ.")
    rc, owner, bary = (
        vectors[name] for name in ("texel_rows_columns", "face_owner", "barycentric")
    )
    linear = rc[:, 0].astype(np.int64) * 256 + rc[:, 1]
    if (
        np.any(rc < 0)
        or np.any(rc > 255)
        or np.any(np.diff(linear) <= 0)
        or np.any(owner < 0)
        or np.any(owner >= 300_000)
        or np.any(bary < -1e-8)
        or np.any(bary > 1 + 1e-8)
        or np.any(np.abs(bary.sum(axis=1) - 1) > 1e-8)
        or np.any(vectors["region_bits"] > 15)
        or np.any(vectors["rejection_partition"] > 3)
    ):
        raise ValueError("Saved correspondence indices, weights or region/rejection bits differ.")
    classes = classification[rc[:, 0], rc[:, 1]]
    if np.count_nonzero(classification >= 2) != count or np.any(classes < 2):
        raise ValueError(
            "Saved vectors must exactly cover the original unique-correspondence domain."
        )
    return rc, classes


def _array_hashes(vectors):
    return {
        name: uv._digest(np.ascontiguousarray(vectors[name]).tobytes(order="C"))
        for name in mask.VECTOR_NAMES
    }


def _mask_delta(old, new):
    added, removed = ~old & new, old & ~new
    return {
        "added_pixels": int(added.sum()),
        "removed_pixels": int(removed.sum()),
        "unchanged_pixels": int(np.count_nonzero(old == new)),
    }


def _global_counts(classification):
    return {
        name: int(np.count_nonzero(classification == code)) for name, code in uv.REASONS.items()
    }


def evaluate_counterfactual(candidate, classification, vectors):
    """Recompute a nonusable mask upper bound, preserving every original input."""
    allowed, occluded, base = _candidate_arrays(candidate)
    if (
        not isinstance(classification, np.ndarray)
        or classification.dtype != np.uint8
        or classification.shape != (256, 256)
        or not np.isin(classification, tuple(uv.REASONS.values())).all()
    ):
        raise ValueError("Original classification must be the complete uint8 seven-class atlas.")
    rc, classes = _vector_arrays(vectors, classification)
    hashes = _array_hashes(vectors)
    visible = (classes == 5) | (classes == 6)
    xy = vectors["target_xyz"][visible, :2]
    old_partition = np.zeros(len(rc), np.uint8)
    old_partition[visible] = uv.mask_rejection_partition(allowed, occluded, xy)
    if not np.array_equal(old_partition, vectors["rejection_partition"]) or not np.array_equal(
        old_partition > 0, classes == 5
    ):
        raise ValueError(
            "Original visible mask partition does not reproduce saved classification/vectors."
        )
    old_bits = mask.contributor_bits(candidate["reason"], xy)
    if not np.array_equal(
        (old_bits & 8 != 0).astype(np.uint8) + 2 * (old_bits & 7 != 0).astype(np.uint8),
        old_partition[visible],
    ):
        raise ValueError("Original contributor recipe bits do not reproduce the old partition.")
    no_occlusion = np.zeros(base.shape, bool)
    new_partition = np.zeros(len(rc), np.uint8)
    new_partition[visible] = uv.mask_rejection_partition(base, no_occlusion, xy)
    if not np.array_equal(new_partition[visible], 2 * (old_bits & 7 != 0).astype(np.uint8)):
        raise ValueError("Removing B changed a non-band contributor or geometric visibility.")
    released = (classes == 5) & (new_partition == 0)
    expected_released = np.zeros(len(rc), bool)
    expected_released[visible] = old_bits == 8
    mixed = old_partition == uv.REJECTION_CODES["mixed_contributors"]
    if not np.array_equal(released, expected_released) or np.any(new_partition[mixed] != 2):
        raise ValueError(
            "Only band-only rejection may be released; mixed rejection must remain other-only."
        )
    new_classification = classification.copy()
    new_classification[rc[released, 0], rc[released, 1]] = 6
    new_classes = new_classification[rc[:, 0], rc[:, 1]]
    if not np.array_equal(new_partition > 0, new_classes == 5) or np.any(
        (new_classification != classification)
        & ~((classification == 5) & (new_classification == 6))
    ):
        raise ValueError(
            "Counterfactual changed an unavailable/sampled class or its rejection partition."
        )
    old_counts = uv.region_counts(classification, rc, vectors["region_bits"], old_partition)
    new_counts = uv.region_counts(new_classification, rc, vectors["region_bits"], new_partition)
    regional_changes = {}
    for index, name in enumerate(("all_unique_correspondence", *uv.REGIONS)):
        selected = (
            np.ones(len(rc), bool)
            if index == 0
            else vectors["region_bits"] & (1 << (index - 1)) != 0
        )
        if old_counts[name]["requested"] != new_counts[name]["requested"]:
            raise ValueError("A counterfactual changed an original regional denominator.")
        regional_changes[name] = {
            "requested": old_counts[name]["requested"],
            "released_texels": int(np.count_nonzero(released & selected)),
            "retained_mask_rejected_texels": int(np.count_nonzero((new_classes == 5) & selected)),
            "classification_transition_7x7": np.bincount(
                classes[selected].astype(np.int64) * 7 + new_classes[selected], minlength=49
            )
            .reshape(7, 7)
            .tolist(),
        }
    transitions = np.bincount(
        (classification.astype(np.int64) * 7 + new_classification).ravel(), minlength=49
    ).reshape(7, 7)
    if _array_hashes(vectors) != hashes:
        raise ValueError("Saved correspondence vectors changed during the counterfactual.")
    return {
        "arms": {
            ARMS[0]: {
                "counts": old_counts,
                "global_classification_counts": _global_counts(classification),
            },
            ARMS[1]: {
                "counts": new_counts,
                "global_classification_counts": _global_counts(new_classification),
            },
        },
        "mask_delta": {
            "allowed": _mask_delta(allowed, base),
            "occluded": _mask_delta(occluded, no_occlusion),
        },
        "classification_transition_7x7": transitions.tolist(),
        "released_texels": int(released.sum()),
        "retained_mask_rejected_texels": int(np.count_nonzero(new_classes == 5)),
        "regional_changes": regional_changes,
        "vector_array_sha256": hashes,
        "checks": {
            "only_5_to_6": True,
            "other_classes_unchanged": True,
            "region_denominators_unchanged": True,
            "mixed_contributors_still_rejected": True,
            "geometry_vectors_unchanged": True,
        },
    }


def _baseline_record(inputs, item, old, primary):
    row = item["registration"]
    candidate, comparison = mask._pixel_record(inputs, item)
    if (
        comparison["exact"] is not True
        or comparison != primary["pixel_comparison"]
        or candidate["pixel_counts"] != primary["layer_pixel_counts"]
        or row["mask_review"]["exclusions"] != primary["reviewed_exclusions"]
    ):
        raise ValueError("Historical masks, stages or exclusions differ from the verified replay.")
    if mask._decompose(inputs, item, old, candidate["reason"]) != primary["decomposition"]:
        raise ValueError(
            "Historical contributor decomposition no longer matches the frozen replay."
        )
    vectors = mask.load_vectors(
        inputs.read(old["correspondence"]), old["counts"]["all_unique_correspondence"]["requested"]
    )
    classification = uv._png(inputs.read(row["artifacts"]["classification"]), "L", (256, 256))
    samples = uv.safe_npz(inputs.read(row["artifacts"]["samples"]), uv.SAMPLE_NAMES)
    atlas = uv._png(inputs.read(row["artifacts"]["atlas"]), "RGBA", (256, 256))
    if (
        not np.array_equal(classification, samples["classification"])
        or not np.array_equal(atlas, samples["rgba"])
        or not np.array_equal(samples["coverage"], classification == 6)
        or not np.array_equal(samples["coverage"], atlas[:, :, 3] == 255)
        or np.any(atlas[classification != 6] != 0)
        or np.any((atlas[:, :, 3] != 0) & (atlas[:, :, 3] != 255))
    ):
        raise ValueError(
            "Original PNG/NPZ classification, RGBA or unknown-alpha invariant differs."
        )
    return candidate, classification, vectors


def _invalidate(report, error):
    for row in report["records"]:
        row.pop("baseline", None)
        row.update(
            status="invalidated_input_drift",
            error_code="INPUT_DRIFT",
            detail=str(error),
            sensitivity=None,
        )
    report["summary"].update(
        statuses={"invalidated_input_drift": len(report["records"])},
        baseline_targets=0,
        all_baselines_verified=False,
        candidate_targets=0,
        all_requested_verified=False,
    )
    report["integrity"] = {"all_inputs_unchanged": False, "detail": str(error)}


def _encode(report):
    encoded = mask._encode(report)
    if len(encoded) > uv.META_LIMIT:
        raise ValueError("Sensitivity report exceeds the metadata byte budget.")
    return encoded


def publish_report(output, report, audit):
    """Publish only a new report; a late drift clears every candidate result."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    destination = output / "report.json"
    try:
        audit()
    except (OSError, ValueError) as error:
        _invalidate(report, error)
    else:
        report["integrity"] = {
            "all_inputs_unchanged": True,
            "runtime_unchanged": True,
            "plan_unchanged": True,
            "verified_input_count": len(report["inputs"]),
        }
    with destination.open("xb") as stream:
        stream.write(_encode(report))
    try:
        audit()
    except (OSError, ValueError) as error:
        _invalidate(report, error)
        destination.unlink()
        with destination.open("xb") as stream:
            stream.write(_encode(report))
    return report


def run(args):
    root = Path(args.root).resolve()
    output = uv._output_path(root, args.output_dir)
    plan_name = Path(args.study_plan)
    plan_path = (plan_name if plan_name.is_absolute() else root / plan_name).resolve()
    if root not in plan_path.parents:
        raise ValueError("Study plan must stay within the workspace.")
    with plan_path.open("rb") as stream:
        plan_bytes = stream.read(uv.META_LIMIT + 1)
    if len(plan_bytes) > uv.META_LIMIT:
        raise ValueError("Study plan exceeds the metadata byte budget.")
    plan, runtime = uv._json(plan_bytes), uv.runtime_fingerprint()
    if (
        plan.get("schema_version") != 1
        or plan.get("protocol_id") != PROTOCOL_ID
        or plan.get("runtime") != runtime
        or set(plan["roles"]) != set(ROLES)
    ):
        raise ValueError("Plan protocol, roles or exact runtime fingerprint differs.")
    inputs, roles = uv.Inputs(root, plan["inputs"]), plan["roles"]
    metadata = {name: uv._json(inputs.read(roles[name], uv.META_LIMIT)) for name in ROLES}
    _protocol(metadata["protocol"])
    inherited = derive_input_pins(metadata)
    if any(inputs.pins.get(pin["path"]) != pin for pin in inherited):
        raise ValueError("Freeze omits or changes an inherited mask/audit input.")
    required = (
        {pin["path"] for pin in inherited} | {pin["path"] for pin in roles.values()} | set(SOURCES)
    )
    if not required <= inputs.pins.keys():
        raise ValueError(
            "Freeze omits required evidence, candidate implementation or test sources."
        )
    if any(
        Path(name).suffix.lower() not in {".py", ".json", ".md", ".toml", ".lock"}
        for name in inputs.pins.keys() - required
    ):
        raise ValueError("Arbitrary new binary inputs outside the inherited cohort are forbidden.")
    if any(inputs.pins[name]["sha256"] != digest for name, digest in _LOADED_SOURCE_HASHES.items()):
        raise ValueError("Loaded Python implementation differs from frozen source bytes.")
    selected, old_records = workbench.validate_evidence(inputs, roles, metadata)
    snapshot_error = None
    try:
        for pin in inputs.pins.values():
            limit = (
                uv.BINARY_LIMIT
                if Path(pin["path"]).suffix.lower() in {".png", ".npz"}
                else uv.META_LIMIT
            )
            inputs.read(pin, limit)
    except (OSError, ValueError, KeyError, TypeError) as error:
        snapshot_error = error
    primary_rows = uv._indexed(metadata["mask_report"]["records"])
    records, prepared = [], []
    for item in selected:
        row = item["registration"]
        record = {
            "sample_id": row["sample_id"],
            "source_id": row["source_id"],
            "target_age_condition": row["target_age"],
            "source_age_label": row["source_age_label"],
            "source_age": dict(uv.UNKNOWN_AGE),
            "correspondence": old_records[row["sample_id"]]["correspondence"],
            "source_frame": row["source_frame"],
            "target_input": row["input"],
            "target_fit": row["target_fit"],
            "status": "failed",
            "sensitivity": None,
        }
        try:
            if snapshot_error is not None:
                raise ValueError("Verified full input snapshot unavailable: " + str(snapshot_error))
            primary = primary_rows[row["sample_id"]]
            result = _baseline_record(inputs, item, old_records[row["sample_id"]], primary)
            prepared.append(result)
            record.update(
                status="baseline_verified",
                baseline={
                    name: primary[name]
                    for name in ("pixel_comparison", "layer_pixel_counts", "decomposition")
                },
            )
        except (OSError, ValueError, KeyError, TypeError, IndexError, cv2.error) as error:
            prepared.append(None)
            record.update(
                error_code="BASELINE_VERIFICATION_FAILED",
                error_type=type(error).__name__,
                detail=str(error),
            )
        records.append(record)
        print(
            f"Sensitivity baseline {len(records)}/12: {row['sample_id']} {record['status']}",
            flush=True,
        )
    all_baselines = len(records) == 12 and all(
        row["status"] == "baseline_verified" for row in records
    )
    if all_baselines:
        for record, baseline in zip(records, prepared, strict=True):
            try:
                record["sensitivity"] = evaluate_counterfactual(*baseline)
                if (
                    record["sensitivity"]["arms"][ARMS[0]]["counts"]
                    != old_records[record["sample_id"]]["counts"]
                ):
                    raise ValueError(
                        "Baseline sensitivity counts changed the original regional evidence."
                    )
                record["status"] = "ok"
            except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
                record.update(
                    status="sensitivity_failed",
                    error_code="COUNTERFACTUAL_FAILED",
                    error_type=type(error).__name__,
                    detail=str(error),
                    sensitivity=None,
                )
    complete = all_baselines and all(row["status"] == "ok" for row in records)
    if not complete:
        for record in records:
            record["sensitivity"] = None
            if record["status"] in {"baseline_verified", "ok"}:
                record.update(
                    status="baseline_verified_candidate_blocked", error_code="COHORT_GATE_FAILED"
                )
    report = {
        "schema_version": 1,
        "protocol_id": PROTOCOL_ID,
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        **metadata["protocol"]["flags"],
        "study_plan": {
            "path": plan_path.relative_to(root).as_posix(),
            "bytes": len(plan_bytes),
            "sha256": uv._digest(plan_bytes),
        },
        "roles": roles,
        "inputs": list(inputs.pins.values()),
        "runtime": runtime,
        "arms": list(ARMS),
        "classification_codes": uv.REASONS,
        "rejection_partition_codes": uv.REJECTION_CODES,
        "region_bit_order": list(uv.REGIONS),
        "records": records,
        "summary": {
            "requested_targets": 12,
            "requested_sources": 3,
            "statuses": dict(Counter(row["status"] for row in records)),
            "baseline_targets": sum("baseline" in row for row in records),
            "all_baselines_verified": all_baselines,
            "candidate_targets": sum(row["sensitivity"] is not None for row in records),
            "all_requested_verified": complete,
        },
        "interpretation": "JSON-only removal-of-B upper bound on known development results. "
        "It deliberately permits uncertain/occluded generated pixels and is not a usable mask, "
        "external-occlusion truth, NO_FACE causal conclusion, human review, "
        "or G3/production acceptance. Saved masks remain unchanged; the candidate is in memory.",
    }

    def audit():
        inputs.recheck()
        with plan_path.open("rb") as stream:
            current = stream.read(uv.META_LIMIT + 1)
        if current != plan_bytes or uv.runtime_fingerprint() != runtime:
            raise ValueError("Study plan, frozen sources/inputs or exact runtime drifted.")

    return publish_report(output, report, audit)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument("--study-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run(args)
        print(mask._encode(report["summary"]).decode("utf-8").strip())
        return 0 if report["summary"]["all_requested_verified"] else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Measure existing N4 atlas display continuity; never run SAM or enable aging.

Support changes were already viewed during N5 planning. New epsilon and
quantization measurements require an explicit frozen input-plan pin list.
"""

# ruff: noqa: E402 -- Standalone entrypoint binds the local backend/tools imports.

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))
sys.path.insert(0, str(_ROOT / "tools"))

import numpy as np
from age_protocol import _load, _path, _pin
from agemorph3d.age_continuity import (
    age_anchors,
    age_weights,
    blend_display_rgba,
    display_step_metrics,
    quantize_display_rgba,
    sam_integer_condition,
    sample_display_rgba,
    support_metrics,
    validate_age,
)
from PIL import Image

_EXPECTED = (37, 10, 27)
_EPSILONS = (1.0, 0.1, 0.01, 0.001)
_GEOMETRY_HASHES = (
    "source_positions_sha256",
    "source_normals_sha256",
    "source_indices_sha256",
    "gltf_uv_sha256",
)


def _verify_pins(root: Path, value: object, checked: set) -> None:
    if isinstance(value, dict):
        if {"path", "sha256", "bytes"} <= value.keys():
            key = (value["path"], value["sha256"], value["bytes"])
            if key not in checked:
                _pin(root, _path(root, value["path"]), value["sha256"], value["bytes"])
                checked.add(key)
        for child in value.values():
            _verify_pins(root, child, checked)
    elif isinstance(value, list):
        for child in value:
            _verify_pins(root, child, checked)


def load_inputs(args) -> tuple[dict, dict, set]:
    """Verify the pre-measurement list and all referenced N4 evidence."""
    plan = _load(args.study_plan)
    report_pin = _pin(args.root, args.registration_report, args.registration_sha256)
    pins = plan["inputs"]
    if (
        plan["protocol_id"] != "agemorph3d-age-continuity-v1"
        or not isinstance(pins, list)
        or not pins
        or any(not isinstance(pin, dict) or set(pin) != {"path", "sha256", "bytes"} for pin in pins)
        or report_pin not in pins
    ):
        raise ValueError("Frozen continuity plan must explicitly pin the supplied N4 report.")
    checked: set = set()
    _verify_pins(args.root, pins, checked)
    report = _load(args.registration_report)
    if (
        report["protocol_id"] != "agemorph3d-target-uv-v1"
        or report["research_only"] is not True
        or report["service_ready"] is not False
        or report["g3_complete"] is not False
        or report["age_texture_quality_accepted"] is not False
    ):
        raise ValueError("Continuity inputs must retain the N4 research-only acceptance boundary.")
    rows = report["records"]
    if (
        len(rows) != _EXPECTED[0]
        or len({row["sample_id"] for row in rows}) != len(rows)
        or len({row["source_id"] for row in rows}) != _EXPECTED[1]
    ):
        raise ValueError("Continuity requests differ from the complete frozen N4 cohort.")
    _verify_pins(args.root, report, checked)
    return report, report_pin, checked


def _atlas(root: Path, row: dict, invariants: dict) -> np.ndarray:
    if row["asset_mode"] != "static" or row["capabilities"] != {
        "age_morph": False,
        "age_texture": False,
    }:
        raise ValueError("Selected source geometry must remain static with age capabilities false.")
    if row["source_age"] != {"value": None, "method": "unknown", "calibration_id": None}:
        raise ValueError("Research filename source age must not replace API unknown source age.")
    if {name: row[name] for name in _GEOMETRY_HASHES} != invariants:
        raise ValueError("Source geometry or common UV changed between N4 age targets.")
    with np.load(_path(root, row["artifacts"]["samples"]["path"]), allow_pickle=False) as saved:
        rgba, coverage, classification, uv = (
            saved[name].copy() for name in ("rgba", "coverage", "classification", "gltf_uv")
        )
    if (
        rgba.shape != (256, 256, 4)
        or coverage.dtype != np.bool_
        or coverage.shape != rgba.shape[:2]
        or classification.dtype != np.uint8
        or classification.shape != coverage.shape
        or not np.isin(classification, np.arange(7)).all()
        or not np.array_equal(coverage, classification == 6)
        or not np.array_equal(rgba[:, :, 3], coverage.astype(np.uint8) * 255)
        or not np.all(rgba[~coverage] == 0)
        or uv.dtype != np.float32
        or uv.ndim != 2
        or uv.shape[1] != 2
        or not np.isfinite(uv).all()
        or hashlib.sha256(uv.astype("<f4").tobytes()).hexdigest() != row["gltf_uv_sha256"]
    ):
        raise ValueError("N4 arrays must preserve common UV, classification and unknown RGBA zero.")
    with Image.open(_path(root, row["artifacts"]["atlas"]["path"])) as image:
        if image.mode != "RGBA" or not np.array_equal(np.asarray(image), rgba):
            raise ValueError("N4 pinned atlas PNG differs from its saved RGBA samples.")
    # Also validates uint8, binary alpha and no hidden RGB in unknown pixels.
    support_metrics(rgba, rgba)
    rgba.setflags(write=False)
    return rgba


def _interval(source_id: str, left: dict, right: dict, atlases: dict) -> dict:
    lo, hi = left["target_age"], right["target_age"]
    row = {"source_id": source_id, "left_age": lo, "right_age": hi, "status": "failed"}
    if left["sample_id"] not in atlases or right["sample_id"] not in atlases:
        return {**row, "error_code": "ENDPOINT_ATLAS_UNAVAILABLE"}
    a, b = atlases[left["sample_id"]], atlases[right["sample_id"]]
    midpoint, epsilon = (lo + hi) / 2, min(0.001, (hi - lo) / 4)
    before = blend_display_rgba(a, b, (midpoint - epsilon - lo) / (hi - lo))
    after = blend_display_rgba(a, b, (midpoint + epsilon - lo) / (hi - lo))
    fractional_age = lo + 0.5
    weights = age_weights(fractional_age, (lo, hi))
    try:
        sam_integer_condition(fractional_age)
    except ValueError:
        direct_sam_rejected = True
    else:
        raise ValueError("Fractional display probe must be rejected as direct SAM conditioning.")
    if not (
        np.array_equal(quantize_display_rgba(blend_display_rgba(a, b, 0)), a)
        and np.array_equal(quantize_display_rgba(blend_display_rgba(a, b, 1)), b)
    ):
        raise ValueError("Display quantization did not preserve binary endpoint atlases.")
    return {
        **row,
        "status": "ok",
        **support_metrics(a, b),
        "threshold_probe_age": midpoint,
        "threshold_probe_epsilon_years": epsilon,
        "threshold_crossing": display_step_metrics(before, after),
        "fractional_display_age": fractional_age,
        "fractional_display_weights": weights.tolist(),
        "fractional_direct_sam_rejected": direct_sam_rejected,
        "endpoint_uint8_rgba_exact": True,
        "original_source_texture_reset_verified": False,
    }


def _epsilon_probes(source_id: str, by_age: dict) -> list[dict]:
    if not by_age:
        return []
    anchors, records = sorted(by_age), []
    for anchor in anchors:
        at_anchor = sample_display_rgba(by_age, anchor)
        for epsilon in _EPSILONS:
            for side, sign in (("left", -1), ("right", 1)):
                age = anchor + sign * epsilon
                row = {
                    "source_id": source_id,
                    "anchor_age": anchor,
                    "side": side,
                    "epsilon_years": epsilon,
                    "probe_age": age,
                    "anchor_kind": "existing_integer_sam_atlas_not_original_source",
                }
                if not anchors[0] <= age <= anchors[-1]:
                    records.append({**row, "status": "outside_anchor_coverage"})
                    continue
                display = sample_display_rgba(by_age, age)
                records.append({**row, "status": "ok", **display_step_metrics(at_anchor, display)})
    return records


def run(args) -> dict:
    if args.output_dir.exists():
        raise FileExistsError("Output already exists; prior continuity evidence is preserved.")
    registration, registration_pin, checked = load_inputs(args)
    groups, atlases, atlas_records = defaultdict(list), {}, []
    for row in registration["records"]:
        source_id = row["source_id"]
        sam_integer_condition(row["target_age"])
        validate_age(row["source_age_label"], allow_unknown=True)
        groups[source_id].append(row)
        result = {"sample_id": row["sample_id"], "source_id": source_id, "status": "failed"}
        if row["status"] != "ok":
            atlas_records.append(
                {**result, "error_code": "RETAINED_N4_REGISTRATION_FAILURE", "original_record": row}
            )
            continue
        try:
            atlases[row["sample_id"]] = _atlas(
                args.root, row, registration["source_geometry_invariants"][source_id]
            )
            atlas_records.append({**result, "status": "ok"})
        except (OSError, ValueError, KeyError, TypeError) as error:
            atlas_records.append(
                {
                    **result,
                    "error_code": "ATLAS_VALIDATION_FAILED",
                    "error_type": type(error).__name__,
                    "detail": str(error),
                }
            )
    intervals, probes, sources = [], [], []
    for source_id, rows in groups.items():
        rows.sort(key=lambda row: row["target_age"])
        ages = [row["target_age"] for row in rows]
        if len(set(ages)) != len(ages) or len({row["source_age_label"] for row in rows}) != 1:
            raise ValueError("Per-source target ages must be unique and source labels unchanged.")
        source_age = rows[0]["source_age_label"]
        by_age = {
            row["target_age"]: atlases[row["sample_id"]]
            for row in rows
            if row["sample_id"] in atlases
        }
        # A missing requested anchor is not silently bridged by a wider interval.
        for left, right in zip(rows, rows[1:], strict=False):
            intervals.append(_interval(source_id, left, right, atlases))
        if len(by_age) == len(rows):
            probes.extend(_epsilon_probes(source_id, by_age))
        sources.append(
            {
                "source_id": source_id,
                "source_age_label": source_age,
                "generated_anchor_ages": ages,
                "policy_anchor_ages_including_original_source": age_anchors(ages, source_age),
                "geometry_route": "static_fallback",
                "research_source_age_label_known": source_age is not None,
                "api_absolute_age_request_enabled": False,
                "real_original_source_asset_reset": {
                    "status": "missing",
                    "reason": "N4 contains generated atlases; an original source texture/GLB reset "
                    "asset is not supplied to this probe.",
                },
                "same_age_sam_is_original_source": False,
                "source_geometry_consistency_basis": (
                    "pinned N4 canonical array hashes; no mesh edits"
                ),
            }
        )
    if len(intervals) != _EXPECTED[2]:
        raise ValueError("Adjacent interval count differs from the complete frozen N4 cohort.")
    measured = [row for row in intervals if row["status"] == "ok"]
    complete = (
        bool(measured) and len(measured) == len(intervals) and len(atlases) == len(atlas_records)
    )
    summary = {
        "requested_targets": len(atlas_records),
        "sources": len(sources),
        "atlas_statuses": dict(Counter(row["status"] for row in atlas_records)),
        "adjacent_intervals": len(intervals),
        "measured_intervals": len(measured),
        "intervals_with_support_change": sum(row["support_xor_texels"] > 0 for row in measured),
        "support_xor_range": (
            [
                min(row["support_xor_texels"] for row in measured),
                max(row["support_xor_texels"] for row in measured),
            ]
            if measured
            else None
        ),
        "epsilon_probes": len(probes),
        "epsilon_probe_statuses": dict(Counter(row["status"] for row in probes)),
        "fractional_display_probes": len(measured),
        "fractional_sam_requests_rejected": sum(
            row["fractional_direct_sam_rejected"] for row in measured
        ),
        "real_source_resets_measured": 0,
        "missing_real_source_reset_assets": len(sources),
        "all_requested_measurements_complete": complete,
    }
    report = {
        "schema_version": 1,
        "protocol_id": "agemorph3d-age-continuity-v1",
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "inputs": {
            "registration_report": registration_pin,
            "study_plan": _pin(args.root, args.study_plan),
        },
        "verified_unique_file_pins": len(checked),
        "prior_support_diagnostics_seen": True,
        "epsilon_steps_years": _EPSILONS,
        "geometry_route": "static_fallback",
        "interpolation": "existing SAM integer-condition atlases; linear-light premultiplied "
        "floating alpha display proposal, not fractional SAM generation",
        "current_viewer_supports_blend_interpolation": False,
        "current_n4_material": "MASK alphaCutoff=0.5; visibility can jump",
        "source_reset_evidence": "synthetic object/PNG/GLB tests only; actual original source "
        "texture assets are missing, no same-age SAM substitution",
        "atlas_records": atlas_records,
        "sources": sources,
        "intervals": intervals,
        "epsilon_probes": probes,
        "retained_prior_fit_failures": registration["retained_prior_fit_failures"],
        "summary": summary,
        "research_only": True,
        "service_ready": False,
        "g3_complete": False,
        "age_morph_quality_accepted": False,
        "age_texture_quality_accepted": False,
        "identity_quality_accepted": False,
        "visual_seam_quality_accepted": False,
        "production_continuity_accepted": False,
        "years_calibrated": False,
        "new_sam_inference": False,
        "training": False,
        "holdout_age_results_opened": False,
        "limitations": [
            "Support changes were viewed before this study-plan freeze.",
            "Generated anchor age is a condition, not verified appearance age.",
            "Float display continuity does not establish current MASK visibility "
            "continuity or correct age/identity/seam quality.",
            "Original source texture reset is unmeasured, including fractional "
            "source ages; strict synthetic reset tests do not replace real evidence.",
        ],
    }
    encoded = (json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir / "report.json").open("xb") as stream:
        stream.write(encoded)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument(
        "--registration-report",
        default="output/research/age-stage4-20261021/registration-final/report.json",
    )
    parser.add_argument("--registration-sha256", required=True)
    parser.add_argument("--study-plan", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    try:
        for name in ("registration_report", "study_plan", "output_dir"):
            setattr(args, name, _path(args.root, getattr(args, name)))
        report = run(args)
        print(json.dumps(report["summary"], ensure_ascii=True))
        return 0 if report["summary"]["all_requested_measurements_complete"] else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"{type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

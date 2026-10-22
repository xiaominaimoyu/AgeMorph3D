"""Audit pinned N0--N6 development evidence; never enable production capabilities.

This version deliberately has no quality-signoff input. Historical research
booleans, proxy scores and synthetic contracts cannot supply independent quality
or license acceptance. Models and historical descendant assets are not rerun.
"""

# ruff: noqa: E402 -- Standalone CLI uses the checked-out backend and tools.

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend" / "src"))
sys.path.insert(0, str(_ROOT / "tools"))

from age_protocol import _path, _pin
from agemorph3d.g3_acceptance import Check, evaluate_g3

PROTOCOL_ID = "agemorph3d-g3-acceptance-v1"
ROLES = ("evaluation", "shape", "uv", "continuity", "engineering", "source_reset")
_PROTOCOLS = {
    "evaluation": "agemorph3d-age-research-v1",
    "shape": "agemorph3d-age-shape-comparison-v1",
    "uv": "agemorph3d-target-uv-v1",
    "continuity": "agemorph3d-age-continuity-v1",
    "source_reset": "agemorph3d-source-reset-v1",
}
_SOURCES = (
    "backend/src/agemorph3d/g3_acceptance.py",
    "backend/src/agemorph3d/app.py",
    "backend/src/agemorph3d/runtime.py",
    "backend/src/agemorph3d/model_lifecycle.py",
    "backend/src/agemorph3d/schemas.py",
    "backend/src/agemorph3d/reconstruction.py",
    "backend/src/agemorph3d/age_continuity.py",
    "backend/src/agemorph3d/aging_sessions.py",
    "tools/age_protocol.py",
    "tools/g3_acceptance_probe.py",
    "tools/source_reset_probe.py",
)


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON constant is not allowed: {value}")


def _json(path: Path) -> dict:
    if path.stat().st_size > 8 * 1024**2:
        raise ValueError("Audit JSON inputs must not exceed 8 MiB.")
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise ValueError("Audit inputs must be JSON objects.")
    return value


def _verified(root: Path, pin: dict) -> dict:
    if (
        not isinstance(pin, dict)
        or set(pin) != {"path", "sha256", "bytes"}
        or not isinstance(pin["path"], str)
        or not isinstance(pin["sha256"], str)
        or len(pin["sha256"]) != 64
        or any(c not in "0123456789abcdef" for c in pin["sha256"])
        or type(pin["bytes"]) is not int
        or pin["bytes"] < 1
    ):
        raise ValueError("Pins require a relative path, lowercase SHA-256 and positive byte count.")
    path = _path(root, pin["path"])
    if path.relative_to(root).as_posix() != pin["path"]:
        raise ValueError("Pins must use canonical workspace-relative paths.")
    return _pin(root, path, pin["sha256"], pin["bytes"])


def load_inputs(root: Path, plan_path: Path) -> tuple[dict, dict, dict]:
    plan = _json(plan_path)
    if (
        plan.get("protocol_id") != PROTOCOL_ID
        or plan.get("observations_previously_seen") is not True
        or set(plan.get("reports", {})) != set(ROLES)
    ):
        raise ValueError(
            "Freeze all six report roles and disclose the prior development observations."
        )
    protocol_pin = _verified(root, plan["protocol"])
    protocol = _json(_path(root, protocol_pin["path"]))
    if (
        protocol.get("protocol_id") != PROTOCOL_ID
        or protocol.get("schema_version") != 1
        or protocol.get("report_roles") != list(ROLES)
        or protocol.get("required_source_files") != list(_SOURCES)
    ):
        raise ValueError("The audit protocol or required source scope is unsupported.")
    source_pins = plan.get("source_files")
    if (
        not isinstance(source_pins, list)
        or len(source_pins) != len(_SOURCES)
        or {pin.get("path") for pin in source_pins if isinstance(pin, dict)} != set(_SOURCES)
    ):
        raise ValueError("Freeze every required current source file exactly once.")
    for pin in source_pins:
        _verified(root, pin)
    report_pins, reports = {}, {}
    for role in ROLES:
        report_pins[role] = _verified(root, plan["reports"][role])
        report = _json(_path(root, report_pins[role]["path"]))
        if role in _PROTOCOLS and report.get("protocol_id") != _PROTOCOLS[role]:
            raise ValueError(f"Unsupported {role} report protocol.")
        reports[role] = report
    cohort_pin = _verified(root, plan["cohort_manifest"])
    reports["cohort"] = _json(_path(root, cohort_pin["path"]))
    if (
        reports["cohort"]["protocol_id"] != _PROTOCOLS["evaluation"]
        or reports["cohort"]["inputs"]["protocol"] != report_pins["evaluation"]
        or cohort_pin != reports["shape"]["inputs"]["protocol_manifest"]
    ):
        raise ValueError("N0 evaluation protocol must bind the shared cohort manifest.")
    _associations(reports, report_pins)
    source_ids = {row["source_id"] for row in reports["uv"]["records"]}
    reset_ids = {row["sample_id"] for row in reports["source_reset"]["records"]}
    cohort_ids = {
        row["sample_id"]
        for row in reports["cohort"]["bridge_cases"]
        if row["source_status"] == "passed"
    }
    if source_ids != reset_ids or reset_ids != cohort_ids:
        raise ValueError("Reset, UV and N0 source cohorts must agree exactly.")
    return (
        plan,
        reports,
        {
            "protocol": protocol_pin,
            "reports": report_pins,
            "source_files": source_pins,
            "cohort_manifest": cohort_pin,
        },
    )


def _associations(reports: dict, pins: dict) -> None:
    """Reject detached evidence before classifying research-only observations."""
    shape, uv, continuity, engineering, reset = (
        reports[key] for key in ("shape", "uv", "continuity", "engineering", "source_reset")
    )
    if (
        shape["inputs"]["protocol_manifest"] != uv["inputs"]["protocol_manifest"]
        or shape["inputs"]["generated_report"] != uv["inputs"]["generated_report"]
        or continuity["inputs"]["registration_report"] != pins["uv"]
        or pins["continuity"] not in engineering["evidence"]
        or reset["inputs"]["protocol_manifest"] != uv["inputs"]["protocol_manifest"]
        or reset["inputs"]["generated_report"] != uv["inputs"]["generated_report"]
        or reset["inputs"]["uv"] != uv["inputs"]["uv"]
    ):
        raise ValueError("Report lineage or source cohort differs between the frozen stages.")
    # These report versions establish development/engineering facts only. An
    # edited true flag is not a new independent evaluation or quality signoff.
    false_flags = {
        "evaluation": ("service_ready", "years_calibrated", "identity_accepted", "g3_complete"),
        "shape": (
            "service_ready",
            "g3_complete",
            "identity_quality_accepted",
            "years_calibrated",
            "quality_thresholds_established",
            "independent_evaluation",
        ),
        "uv": (
            "service_ready",
            "g3_complete",
            "age_texture_quality_accepted",
            "identity_quality_accepted",
            "visual_seam_quality_accepted",
        ),
        "continuity": ("service_ready", "g3_complete", "production_continuity_accepted"),
        "engineering": (
            "table5_full_production_exit_passed",
            "real_sam_to_uv_service_integrated",
            "production_age_capabilities_enabled",
            "g3_complete",
        ),
        "source_reset": ("service_ready", "g3_complete"),
    }
    for role, keys in false_flags.items():
        if any(reports[role].get(key) is not False for key in keys):
            raise ValueError(f"{role} research flags cannot supply quality/production acceptance.")
    if any(
        reports[role].get("research_only") is not True for role in ("shape", "uv", "source_reset")
    ):
        raise ValueError("Research reports must retain their research-only scope.")
    if (
        shape["selection"]["research_route_choice"] != "static_fallback"
        or shape["production_route_selected"] is not None
        or continuity["geometry_route"] != "static_fallback"
        or engineering["shape_route"] != "static_fallback"
    ):
        raise ValueError("This audit version supports the existing static fallback baseline only.")


def _source_resets(root: Path, report: dict, cohort: dict) -> dict:
    """Verify new original asset bytes, preserving the unknown API age semantics."""
    summary, rows = report["summary"], report["records"]
    if (
        len(rows) != 10
        or len({row["sample_id"] for row in rows}) != 10
        or summary["requested_sources"] != 10
        or report["source_age_api_policy"] != "unknown"
    ):
        raise ValueError(
            "Source-reset report must retain all ten original sources and unknown API age."
        )
    counts = {
        "assets_created": 0,
        "known_label_resets_passed": 0,
        "unknown_age_rejected": 0,
        "failed_sources": 0,
    }
    cases = {
        row["sample_id"]: row for row in cohort["bridge_cases"] if row["source_status"] == "passed"
    }
    for row in rows:
        if row["source_age"] != {"value": None, "method": "unknown", "calibration_id": None}:
            raise ValueError("Mirror filename age must never become API SourceAge provenance.")
        if row["status"] == "ok":
            if set(row["artifacts"]) != {"glb", "atlas"}:
                raise ValueError("Original assets require exactly the GLB and PNG pins.")
            for pin in row["artifacts"].values():
                _verified(root, pin)
            if any(
                row["glb_roundtrip"].get(key) is not True
                for key in ("arrays_exact", "embedded_png_exact", "rgba_exact")
            ):
                raise ValueError(
                    "Original GLB arrays, embedded PNG and decoded RGBA must roundtrip."
                )
            counts["assets_created"] += 1
        else:
            counts["failed_sources"] += 1
        if row["label_source_age"] != cases[row["sample_id"]]["source_age"]["value"]:
            raise ValueError("Reset source label differs from its frozen N0 research label.")
        if row["reset_status"] == "passed":
            if row["label_source_age"] is None or row["status"] != "ok":
                raise ValueError(
                    "A passed research reset needs its original assets and known label."
                )
            if any(
                row["reset"].get(key) is not True
                for key in (
                    "object_identity",
                    "glb_bytes_exact",
                    "png_bytes_exact",
                    "shape_coefficients_exact",
                )
            ):
                raise ValueError("Original asset reset must preserve every byte and coefficient.")
            counts["known_label_resets_passed"] += 1
        elif row["reset_status"] == "source_age_unknown":
            if (
                row["label_source_age"] is not None
                or row["reset"].get("error_code") != "SOURCE_AGE_UNKNOWN"
            ):
                raise ValueError("Only unknown source labels can have unknown-age reset status.")
            counts["unknown_age_rejected"] += 1
        elif row["reset_status"] != "failed":
            raise ValueError("Unsupported source-reset status.")
    if any(summary[key] != count for key, count in counts.items()):
        raise ValueError("Source-reset summary differs from its complete records.")
    return counts


def audit(root: Path, reports: dict) -> tuple[dict, dict]:
    evaluation, shape, uv, continuity, engineering, reset = (reports[key] for key in ROLES)
    reset_counts = _source_resets(root, reset, reports["cohort"])
    checks = {
        "evaluation_protocol": Check(
            "passed",
            "N0 freezes identity uses, unknown ages and thresholds; development protocol only.",
            ("evaluation",),
        ),
        "asset_license": Check(
            "missing",
            "No asset-specific final license acceptance is supplied for the complete pipeline.",
            ("evaluation",),
        ),
        "independent_evaluation": Check(
            "missing",
            "Independent evaluation, approved evaluators and frozen domain thresholds unavailable.",
            ("evaluation", "shape"),
        ),
        "identity_quality": Check(
            "missing",
            "Geometry proxies, same-age controls and synthetic contracts cannot sign off identity.",
            ("shape", "engineering"),
        ),
        "strict_reconstruction_acceptance": Check(
            "missing",
            "Strict G1/G2 photo, camera and long-duration quality acceptance missing.",
            ("engineering",),
        ),
        "shape_route": Check(
            "failed",
            "N3 selected static_fallback; neither candidate establishes accepted age geometry.",
            ("shape",),
        ),
        "shape_year_calibration": Check(
            "missing",
            "BFM strength and SAM conditions lack year calibration and full 20--70 acceptance.",
            ("shape",),
        ),
        "shape_quality": Check(
            "missing",
            "No independent age-shape quality acceptance; fitted geometry is a proxy.",
            ("shape",),
        ),
        "shape_continuity": Check(
            "missing",
            "Static geometry is continuous; no accepted varying age-shape route measured.",
            ("shape", "continuity"),
        ),
        "texture_quality": Check(
            "missing",
            "Visual seams, conservative occlusion exclusions and UV coverage remain unsigned.",
            ("uv",),
        ),
        "texture_age_quality": Check(
            "missing",
            "Generated registered pixels have no independent age/identity quality acceptance.",
            ("uv",),
        ),
        "real_service_integration": Check(
            "missing",
            "Real SAM, refit, occlusion review, common UV and production assets not integrated.",
            ("engineering",),
        ),
        "service_resource_lifecycle": Check(
            "missing",
            "CPU worker/synthetic TTL evidence does not cover the real pipeline lifecycle.",
            ("engineering",),
        ),
        "service_performance": Check(
            "missing",
            "No accepted full-pipeline cold/warm/end-to-end latency, memory and recovery budget.",
            ("engineering",),
        ),
    }
    reset_ok = reset_counts == {
        "assets_created": 10,
        "known_label_resets_passed": 8,
        "unknown_age_rejected": 2,
        "failed_sources": 0,
    }
    for key in ("shape_source_reset", "texture_source_reset"):
        checks[key] = Check(
            "passed" if reset_ok else "failed",
            (
                "Offline assets: 8 research-label byte resets and 2 unknown-age rejections; "
                "API ages remain unknown. Production reset is unaccepted."
            )
            if reset_ok
            else "Original source asset/reset measurements incomplete; retain every failed source.",
            ("source_reset",),
        )
    summary = uv["summary"]
    uv_ok = (
        summary["requested_targets"] == 37
        and summary["statuses"] == {"ok": 37}
        and summary["all_requested_glb_roundtrips_passed"] is True
        and len(uv["records"]) == 37
        and len({row["sample_id"] for row in uv["records"]}) == 37
        and all(
            row["status"] == "ok"
            and all(
                row["glb_roundtrip"].get(key) is True
                for key in (
                    "positions_equal_source",
                    "uv_equal_common_atlas",
                    "embedded_png_bytes_equal",
                    "decoded_rgba_equal",
                )
            )
            for row in uv["records"]
        )
    )
    checks["target_uv_registration"] = Check(
        "passed" if uv_ok else "failed",
        "Historical N4 target-own projection/static GLB transport; no visual or age-quality pass.",
        ("uv",),
    )
    support_changes = continuity["summary"]["intervals_with_support_change"]
    checks["rendered_texture_continuity"] = Check(
        "failed",
        f"N5: {support_changes} support-changing intervals; MASK jumps, no BLEND interpolation.",
        ("continuity",),
    )
    if (
        evaluation["thresholds"]["quality_acceptance"] is not None
        or evaluation["grouping"]["independent_external_evaluation"] is not False
        or continuity["current_viewer_supports_blend_interpolation"] is not False
        or engineering["production_aging_status"] != 503
    ):
        raise ValueError(
            "Baseline changed; revise the audit protocol rather than silently reinterpret it."
        )
    observations = {
        "source_reset": reset_counts,
        "shape_route": shape["selection"]["research_route_choice"],
        "uv_historical_summary": summary,
        "continuity_historical_summary": continuity["summary"],
        "engineering_historical_validation": engineering["validation"],
    }
    return evaluate_g3(checks), observations


def run(args) -> dict:
    root = args.root.resolve()
    output = _path(root, args.output_dir)
    relative = output.relative_to(root)
    if relative.parts[:2] != ("output", "research") or len(relative.parts) < 3:
        raise ValueError("Audit output must be a new directory under output/research.")
    if output.exists():
        raise ValueError("Output directory already exists; refusing to overwrite evidence.")
    plan_path = _path(root, args.study_plan)
    plan, reports, pins = load_inputs(root, plan_path)
    result, observations = audit(root, reports)
    result.update(
        protocol_id=PROTOCOL_ID,
        recorded_at_utc=datetime.now(UTC).isoformat(),
        research_only=True,
        study_plan=_pin(root, plan_path),
        inputs=pins,
        observations=observations,
        observations_previously_seen=plan["observations_previously_seen"],
        historical_descendants_revalidated=False,
        current_source_pins_verified=True,
        new_sam_inference=False,
        training=False,
        holdout_age_results_opened=False,
    )
    # Do all input/schema/measurement checks before creating new output.
    encoded = (json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    output.mkdir(parents=True, exist_ok=False)
    with (output / "report.json").open("xb") as stream:
        stream.write(encoded)
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=_ROOT)
    parser.add_argument("--study-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = run(args)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"G3 audit rejected: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "g3_complete": report["g3_complete"],
                "production_enabled": report["production_enabled"],
                "components": {key: value["status"] for key, value in report["components"].items()},
            }
        )
    )
    # Success means the audit ran, not that G3 passed. Report contains all gaps.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

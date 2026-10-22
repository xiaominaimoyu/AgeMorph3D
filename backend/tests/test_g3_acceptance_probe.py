"""Synthetic report-integrity tests; no real inputs, photos or models are read."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools/g3_acceptance_probe.py"
_SPEC = importlib.util.spec_from_file_location("g3_acceptance_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")


@pytest.fixture
def case(tmp_path):
    root = tmp_path
    plan_path = root / "plan.json"
    shared = {}
    generated = {"path": "historical-fits.json", "sha256": "b" * 64, "bytes": 43}
    uv = {"path": "historical-uv.npz", "sha256": "c" * 64, "bytes": 44}
    reports = {
        "evaluation": {
            "protocol_id": probe._PROTOCOLS["evaluation"],
            "service_ready": False,
            "years_calibrated": False,
            "identity_accepted": False,
            "g3_complete": False,
            "thresholds": {"quality_acceptance": None},
            "grouping": {"independent_external_evaluation": False},
        },
        "shape": {
            "protocol_id": probe._PROTOCOLS["shape"],
            "research_only": True,
            "inputs": {"protocol_manifest": shared, "generated_report": generated},
            "service_ready": False,
            "g3_complete": False,
            "identity_quality_accepted": False,
            "years_calibrated": False,
            "quality_thresholds_established": False,
            "independent_evaluation": False,
            "production_route_selected": None,
            "selection": {"research_route_choice": "static_fallback"},
        },
        "uv": {
            "protocol_id": probe._PROTOCOLS["uv"],
            "research_only": True,
            "inputs": {"protocol_manifest": shared, "generated_report": generated, "uv": uv},
            "service_ready": False,
            "g3_complete": False,
            "age_texture_quality_accepted": False,
            "identity_quality_accepted": False,
            "visual_seam_quality_accepted": False,
            "summary": {
                "requested_targets": 37,
                "statuses": {"ok": 37},
                "all_requested_glb_roundtrips_passed": True,
            },
            "records": [
                {
                    "sample_id": f"target-{i}",
                    "source_id": f"source-{i % 10}",
                    "status": "ok",
                    "glb_roundtrip": {
                        "positions_equal_source": True,
                        "uv_equal_common_atlas": True,
                        "embedded_png_bytes_equal": True,
                        "decoded_rgba_equal": True,
                    },
                }
                for i in range(37)
            ],
        },
        "continuity": {
            "protocol_id": probe._PROTOCOLS["continuity"],
            "service_ready": False,
            "g3_complete": False,
            "production_continuity_accepted": False,
            "geometry_route": "static_fallback",
            "current_viewer_supports_blend_interpolation": False,
            "summary": {"intervals_with_support_change": 27},
            "inputs": {},
        },
        "engineering": {
            "table5_full_production_exit_passed": False,
            "real_sam_to_uv_service_integrated": False,
            "production_age_capabilities_enabled": False,
            "g3_complete": False,
            "shape_route": "static_fallback",
            "production_aging_status": 503,
            "validation": {"backend_tests": 1156, "synthetic_browser": True},
            "evidence": [],
        },
        "source_reset": {
            "protocol_id": probe._PROTOCOLS["source_reset"],
            "research_only": True,
            "service_ready": False,
            "g3_complete": False,
            "source_age_api_policy": "unknown",
            "inputs": {"protocol_manifest": shared, "generated_report": generated, "uv": uv},
            "summary": {
                "requested_sources": 10,
                "assets_created": 10,
                "known_label_resets_passed": 8,
                "unknown_age_rejected": 2,
                "failed_sources": 0,
            },
            "records": [],
        },
    }
    for i in range(10):
        path = root / "assets" / f"{i}.asset"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(f"synthetic original {i}".encode())
        reports["source_reset"]["records"].append(
            {
                "sample_id": f"source-{i}",
                "status": "ok",
                "source_age": {"value": None, "method": "unknown", "calibration_id": None},
                "label_source_age": 42.5 if i < 8 else None,
                "reset_status": "passed" if i < 8 else "source_age_unknown",
                "reset": {
                    "object_identity": True,
                    "glb_bytes_exact": True,
                    "png_bytes_exact": True,
                    "shape_coefficients_exact": True,
                }
                if i < 8
                else {"error_code": "SOURCE_AGE_UNKNOWN"},
                "glb_roundtrip": {
                    "arrays_exact": True,
                    "embedded_png_exact": True,
                    "rgba_exact": True,
                },
                "artifacts": {"glb": probe._pin(root, path), "atlas": probe._pin(root, path)},
            }
        )
    protocol = {
        "schema_version": 1,
        "protocol_id": probe.PROTOCOL_ID,
        "report_roles": list(probe.ROLES),
        "required_source_files": list(probe._SOURCES),
    }
    write_json(root / "protocol.json", protocol)
    for path in probe._SOURCES:
        source = root / path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# synthetic source pin\n", encoding="utf-8")

    def repin():
        pins = {}
        for role in probe.ROLES:
            if role == "continuity":
                reports[role]["inputs"]["registration_report"] = pins["uv"]
            if role == "engineering":
                reports[role]["evidence"] = [pins["continuity"]]
            path = root / f"{role}.json"
            write_json(path, reports[role])
            pins[role] = probe._pin(root, path)
        cohort = {
            "protocol_id": probe._PROTOCOLS["evaluation"],
            "inputs": {"protocol": pins["evaluation"]},
            "bridge_cases": [
                {
                    "sample_id": f"source-{i}",
                    "source_status": "passed",
                    "source_age": {"value": 42.5 if i < 8 else None},
                }
                for i in range(10)
            ],
        }
        write_json(root / "cohort.json", cohort)
        shared.update(probe._pin(root, root / "cohort.json"))
        # shared dictionaries above refer to this one N0 manifest; repin the
        # downstream reports and their links after the manifest has its hash.
        for role in probe.ROLES[1:]:
            if role == "continuity":
                reports[role]["inputs"]["registration_report"] = pins["uv"]
            if role == "engineering":
                reports[role]["evidence"] = [pins["continuity"]]
            write_json(root / f"{role}.json", reports[role])
            pins[role] = probe._pin(root, root / f"{role}.json")
        plan = {
            "protocol_id": probe.PROTOCOL_ID,
            "observations_previously_seen": True,
            "protocol": probe._pin(root, root / "protocol.json"),
            "reports": pins,
            "cohort_manifest": probe._pin(root, root / "cohort.json"),
            "source_files": [probe._pin(root, root / path) for path in probe._SOURCES],
        }
        write_json(plan_path, plan)
        return plan

    repin()
    args = SimpleNamespace(
        root=root, study_plan=plan_path, output_dir=root / "output/research/audit"
    )
    return SimpleNamespace(root=root, args=args, reports=reports, repin=repin)


def test_research_transport_and_reset_passes_do_not_sign_off_quality_or_service(case):
    report = probe.run(case.args)
    assert report["checks"]["target_uv_registration"]["status"] == "passed"
    assert report["checks"]["texture_source_reset"]["status"] == "passed"
    assert report["components"]["shape"]["status"] == "failed"
    assert report["components"]["texture"]["status"] == "failed"
    assert report["components"]["continuity"]["status"] == "failed"
    assert report["components"]["identity"]["status"] == "missing"
    assert report["candidate_capabilities"] == {"age_morph": False, "age_texture": False}
    assert report["g3_complete"] is report["production_enabled"] is False
    assert report["historical_descendants_revalidated"] is False
    assert (case.args.output_dir / "report.json").is_file()


@pytest.mark.parametrize("file", ["shape.json", "assets/0.asset", probe._SOURCES[0]])
def test_stale_reports_new_assets_or_current_sources_are_rejected_before_output(case, file):
    (case.root / file).write_bytes(b"changed")
    with pytest.raises(ValueError, match="mismatch"):
        probe.run(case.args)
    assert not case.args.output_dir.exists()


def test_missing_report_is_rejected_before_output(case):
    (case.root / "uv.json").unlink()
    with pytest.raises(OSError):
        probe.run(case.args)
    assert not case.args.output_dir.exists()


def test_detached_lineage_is_rejected_even_with_matching_file_hash(case):
    case.reports["source_reset"]["inputs"]["uv"] = {
        "path": "different.npz",
        "sha256": "e" * 64,
        "bytes": 4,
    }
    case.repin()
    with pytest.raises(ValueError, match="lineage"):
        probe.run(case.args)


@pytest.mark.parametrize(
    "role,flag",
    [
        ("shape", "independent_evaluation"),
        ("uv", "identity_quality_accepted"),
        ("engineering", "production_age_capabilities_enabled"),
    ],
)
def test_edited_research_acceptance_boolean_cannot_promote_quality(case, role, flag):
    case.reports[role][flag] = True
    case.repin()
    with pytest.raises(ValueError, match="cannot supply"):
        probe.run(case.args)
    assert not case.args.output_dir.exists()


def test_mirror_label_cannot_become_api_user_age(case):
    case.reports["source_reset"]["records"][0]["source_age"] = {
        "value": 42.5,
        "method": "user",
        "calibration_id": None,
    }
    case.repin()
    with pytest.raises(ValueError, match="SourceAge"):
        probe.run(case.args)


def test_duplicate_cohort_source_is_rejected(case):
    case.reports["source_reset"]["records"][1]["sample_id"] = "source-0"
    case.repin()
    with pytest.raises(ValueError, match="cohorts|ten original"):
        probe.run(case.args)


@pytest.mark.parametrize("field", ["artifacts", "reset", "glb_roundtrip"])
def test_technical_reset_needs_both_asset_pins_and_exactness_measurements(case, field):
    case.reports["source_reset"]["records"][0][field] = {}
    case.repin()
    with pytest.raises(ValueError):
        probe.run(case.args)
    assert not case.args.output_dir.exists()


def test_substituted_evaluation_protocol_rejected_even_when_repinned(case):
    plan = case.repin()
    changed = {**case.reports["evaluation"], "frozen_on": "different-protocol"}
    write_json(case.root / "substituted.json", changed)
    plan["reports"]["evaluation"] = probe._pin(case.root, case.root / "substituted.json")
    write_json(case.args.study_plan, plan)
    with pytest.raises(ValueError, match="N0 evaluation"):
        probe.run(case.args)


def test_incomplete_new_reset_is_reported_without_hiding_failed_source(case):
    report = case.reports["source_reset"]
    report["records"][0].update(status="failed", reset_status="failed", artifacts={})
    report["summary"].update(assets_created=9, known_label_resets_passed=7, failed_sources=1)
    case.repin()
    actual = probe.run(case.args)
    assert actual["checks"]["texture_source_reset"]["status"] == "failed"
    assert actual["observations"]["source_reset"]["failed_sources"] == 1


def test_uv_summary_cannot_hide_missing_historical_measurements(case):
    case.reports["uv"]["records"].pop()
    case.repin()
    report = probe.run(case.args)
    assert report["checks"]["target_uv_registration"]["status"] == "failed"


def test_existing_output_is_never_overwritten(case):
    case.args.output_dir.mkdir(parents=True)
    sentinel = case.args.output_dir / "sentinel"
    sentinel.write_bytes(b"original")
    with pytest.raises(ValueError, match="already exists"):
        probe.run(case.args)
    assert sentinel.read_bytes() == b"original"


@pytest.mark.parametrize("target", ["docs/invalid", "output", "../outside"])
def test_output_stays_in_ignored_research_directory(case, target):
    case.args.output_dir = Path(target)
    with pytest.raises(ValueError):
        probe.run(case.args)


def test_duplicate_source_pin_and_noncanonical_pin_rejected(case):
    plan = case.repin()
    plan["source_files"][-1] = plan["source_files"][0]
    write_json(case.args.study_plan, plan)
    with pytest.raises(ValueError, match="every required"):
        probe.run(case.args)
    plan = case.repin()
    plan["reports"]["shape"]["path"] = "./shape.json"
    write_json(case.args.study_plan, plan)
    with pytest.raises(ValueError, match="canonical"):
        probe.run(case.args)


def test_cli_reports_gaps_as_successful_audit_but_bad_input_as_failure(case):
    args = [
        "--root",
        str(case.root),
        "--study-plan",
        str(case.args.study_plan),
        "--output-dir",
        str(case.args.output_dir),
    ]
    assert probe.main(args) == 0
    assert probe.main(args) == 1

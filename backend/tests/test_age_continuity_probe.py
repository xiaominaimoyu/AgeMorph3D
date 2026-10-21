"""Synthetic pinned N4 continuity probe; never opens real research inputs."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

np = pytest.importorskip("numpy")

_PATH = Path(__file__).resolve().parents[2] / "tools/age_continuity_probe.py"
_SPEC = importlib.util.spec_from_file_location("age_continuity_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "_EXPECTED", (3, 1, 2))
    root = tmp_path
    uv = np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float32)
    import hashlib

    hashes = {
        "source_positions_sha256": "11" * 32,
        "source_normals_sha256": "22" * 32,
        "source_indices_sha256": "33" * 32,
        "gltf_uv_sha256": hashlib.sha256(uv.astype("<f4").tobytes()).hexdigest(),
    }
    rows = []
    for index, age in enumerate((20, 45, 70)):
        rgba = np.zeros((256, 256, 4), dtype=np.uint8)
        rgba[30:80, 30 + index : 80 + index] = [90 + index * 20, 110, 170, 255]
        coverage = rgba[:, :, 3] == 255
        atlas_path, samples_path = root / f"{age}.png", root / f"{age}.npz"
        Image.fromarray(rgba).save(atlas_path)
        np.savez_compressed(
            samples_path,
            rgba=rgba,
            coverage=coverage,
            classification=coverage.astype(np.uint8) * 6,
            gltf_uv=uv,
        )
        rows.append(
            {
                "sample_id": f"source--sam-{age}",
                "source_id": "source",
                "target_age": age,
                "source_age_label": 42.5,
                "status": "ok",
                "asset_mode": "static",
                "source_age": {"value": None, "method": "unknown", "calibration_id": None},
                "capabilities": {"age_morph": False, "age_texture": False},
                **hashes,
                "artifacts": {
                    "atlas": probe._pin(root, atlas_path),
                    "samples": probe._pin(root, samples_path),
                },
            }
        )
    report = {
        "protocol_id": "agemorph3d-target-uv-v1",
        "research_only": True,
        "service_ready": False,
        "g3_complete": False,
        "age_texture_quality_accepted": False,
        "records": rows,
        "source_geometry_invariants": {"source": hashes},
        "retained_prior_fit_failures": [
            {"sample_id": "failed-original", "status": "failed", "error_code": "NO_FACE"}
        ],
    }
    report_path, plan_path = root / "registration.json", root / "study-plan.json"
    args = SimpleNamespace(
        root=root,
        registration_report=report_path,
        study_plan=plan_path,
        output_dir=root / "continuity",
    )

    def repin():
        write_json(report_path, report)
        pin = probe._pin(root, report_path)
        args.registration_sha256 = pin["sha256"]
        write_json(plan_path, {"protocol_id": "agemorph3d-age-continuity-v1", "inputs": [pin]})

    repin()
    return SimpleNamespace(args=args, report=report, repin=repin, root=root)


def test_pinned_probe_reports_support_float_mask_and_fractional_policies_separately(case):
    report = probe.run(case.args)
    assert report["summary"]["all_requested_measurements_complete"]
    assert report["summary"]["requested_targets"] == 3
    assert report["summary"]["adjacent_intervals"] == 2
    assert report["summary"]["fractional_sam_requests_rejected"] == 2
    assert report["summary"]["support_xor_range"] == [100, 100]
    assert all(
        row["threshold_crossing"]["float_mask_visibility_flip_texels"] == 100
        for row in report["intervals"]
    )
    assert all(
        row["threshold_crossing"]["quantized_mask_visibility_flip_texels"] == 100
        for row in report["intervals"]
    )
    assert report["sources"][0]["policy_anchor_ages_including_original_source"] == (
        20,
        42.5,
        45,
        70,
    )
    assert report["sources"][0]["real_original_source_asset_reset"]["status"] == "missing"
    assert report["summary"]["real_source_resets_measured"] == 0
    assert report["prior_support_diagnostics_seen"]
    assert not report["current_viewer_supports_blend_interpolation"]
    assert not report["production_continuity_accepted"] and not report["g3_complete"]
    assert not report["new_sam_inference"] and not report["training"]
    assert report["retained_prior_fit_failures"] == case.report["retained_prior_fit_failures"]
    saved = json.loads((case.args.output_dir / "report.json").read_text("utf-8"))
    assert len(saved["epsilon_probes"]) == 24
    assert saved["summary"]["epsilon_probe_statuses"] == {"outside_anchor_coverage": 8, "ok": 16}
    assert all(
        row["anchor_kind"] == "existing_integer_sam_atlas_not_original_source"
        for row in saved["epsilon_probes"]
    )


def test_unknown_research_source_age_stays_unknown_and_does_not_block_generated_display_audit(case):
    for row in case.report["records"]:
        row["source_age_label"] = None
    case.repin()
    report = probe.run(case.args)
    source = report["sources"][0]
    assert source["source_age_label"] is None
    assert not source["research_source_age_label_known"]
    assert not source["api_absolute_age_request_enabled"]
    assert source["policy_anchor_ages_including_original_source"] == (20, 45, 70)


def test_wrong_report_sha_is_rejected_before_any_output(case):
    case.args.registration_sha256 = "00" * 32
    with pytest.raises(ValueError, match="SHA-256"):
        probe.run(case.args)
    assert not case.args.output_dir.exists()


def test_plan_must_pin_supplied_report_not_just_another_existing_file(case):
    other = case.root / "other.json"
    write_json(other, {})
    write_json(
        case.args.study_plan,
        {"protocol_id": "agemorph3d-age-continuity-v1", "inputs": [probe._pin(case.root, other)]},
    )
    with pytest.raises(ValueError, match="explicitly pin"):
        probe.run(case.args)
    assert not case.args.output_dir.exists()


def test_referenced_atlas_tamper_is_rejected_instead_of_remeasured(case):
    (case.root / "20.png").write_bytes(b"changed atlas")
    with pytest.raises(ValueError, match="SHA-256"):
        probe.run(case.args)
    assert not case.args.output_dir.exists()


def test_geometry_change_retains_failed_target_and_both_adjacent_intervals(case):
    case.report["records"][1]["source_positions_sha256"] = "ff" * 32
    case.repin()
    report = probe.run(case.args)
    assert not report["summary"]["all_requested_measurements_complete"]
    assert report["summary"]["atlas_statuses"] == {"ok": 2, "failed": 1}
    assert report["summary"]["adjacent_intervals"] == 2
    assert report["summary"]["measured_intervals"] == 0
    assert report["epsilon_probes"] == []  # No silent interpolation over missing 45.
    assert all(row["error_code"] == "ENDPOINT_ATLAS_UNAVAILABLE" for row in report["intervals"])


def test_prior_registration_failure_is_retained_without_replacing_its_atlas(case):
    case.report["records"][1] = {
        **case.report["records"][1],
        "status": "failed",
        "error_code": "TARGET_REGISTRATION_FAILED",
    }
    case.repin()
    report = probe.run(case.args)
    failure = report["atlas_records"][1]
    assert failure["error_code"] == "RETAINED_N4_REGISTRATION_FAILURE"
    assert failure["original_record"]["error_code"] == "TARGET_REGISTRATION_FAILED"
    assert not report["summary"]["all_requested_measurements_complete"]


def test_duplicate_target_age_and_fractional_direct_condition_are_rejected(case):
    case.report["records"][1]["target_age"] = 20
    case.repin()
    with pytest.raises(ValueError, match="unique"):
        probe.run(case.args)
    assert not case.args.output_dir.exists()
    case.report["records"][1]["target_age"] = 42.5
    case.repin()
    with pytest.raises(ValueError, match="exact integer"):
        probe.run(case.args)


def test_existing_output_is_preserved_before_any_input_reads(case):
    case.args.output_dir.mkdir()
    sentinel = case.args.output_dir / "sentinel.txt"
    sentinel.write_text("keep", encoding="utf-8")
    case.args.registration_report = case.root / "missing.json"
    with pytest.raises(FileExistsError, match="preserved"):
        probe.run(case.args)
    assert sentinel.read_text("utf-8") == "keep"


def test_main_prints_error_and_nonzero_exit_for_invalid_pin(case, capsys):
    result = probe.main(
        [
            "--root",
            str(case.root),
            "--registration-report",
            "registration.json",
            "--registration-sha256",
            "00" * 32,
            "--study-plan",
            "study-plan.json",
            "--output-dir",
            "new-output",
        ]
    )
    assert result == 1 and "SHA-256 mismatch" in capsys.readouterr().out

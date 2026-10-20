"""Synthetic metadata integrity checks, not real age/identity model acceptance."""

import csv
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools" / "age_protocol.py"
_SPEC = importlib.util.spec_from_file_location("age_protocol", _PATH)
protocol = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(protocol)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_file(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return {"sha256": digest(value), "bytes": len(value)}


@pytest.fixture
def evidence(tmp_path):
    root = tmp_path
    config = {
        "schema_version": 1,
        "protocol_id": "synthetic-protocol",
        "frozen_on": "2026-10-20",
        "source_age_policy": "unknown_stays_null",
        "same_age_policy": "exact_integer_label_only",
        "grouping": {
            "seed": "fixed-test",
            "development_subject_ids": ["001", "002"],
            "calibration_identity_count": 1,
        },
        "target_ages": [20, 45, 70],
        "expected_adult_images": 4,
        "expected_adult_identities": 4,
        "expected_bridge_samples": 3,
        "expected_known_controls": 1,
    }
    config_path = root / "protocol.json"
    write_json(config_path, config)
    subset = root / "data" / "adult.csv"
    rows = []
    for subject in ("001", "002", "003", "004"):
        image = f"images/{subject}A27.JPG"
        pin = write_file(subset.parent / image, subject.encode())
        rows.append(
            dict(
                subject_id=subject,
                age=27,
                image=image,
                sha256=pin["sha256"],
                size_bytes=pin["bytes"],
            )
        )

    def save_csv():
        with subset.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    save_csv()
    checkpoint = "c" * 64
    controls = root / "controls"

    def sam_report(path, aligned_hash, ages):
        runs = []
        for age in ages:
            filename = f"age-{age}.png"
            pin = write_file(path.parent / filename, f"{path}:{age}".encode())
            runs.append(dict(target_age=age, output=filename, output_sha256=pin["sha256"]))
        result = {
            "outputs_written": True,
            "input": {"sha256": aligned_hash},
            "checkpoint": {"sha256": checkpoint},
            "runs": runs,
        }
        write_json(path, result)
        return result

    samples = []
    for sample_id, subject, succeeds in (
        ("known", "001", True),
        ("failure", "002", False),
        ("unknown", None, True),
    ):
        if subject is not None:
            original = root / "data" / "images" / f"{subject}A27.JPG"
        else:
            original = root / "external.bin"
            write_file(original, b"external")
        pin = digest(original.read_bytes())
        case_path = root / "bridge" / sample_id / "report.json"
        status = "passed" if succeeds else "failed"
        case_report = {
            "technical_execution": status,
            "input": {"sha256": pin},
            "error_code": None if succeeds else "NO_FACE",
        }
        sample = {
            "id": sample_id,
            "subject_id": subject,
            "path": original.relative_to(root).as_posix(),
            "age": 27 if subject else None,
            "input_sha256": pin,
            "bridge_report": case_path.relative_to(root).as_posix(),
            "technical_execution": status,
            "error_code": case_report["error_code"],
        }
        if succeeds:
            artifacts = {
                name: write_file(case_path.parent / name, f"{sample_id}:{name}".encode())
                for name in ("aligned.png", "valid-mask.png", "coordinates.json")
            }
            case_report["artifacts"] = artifacts
            aligned_hash = artifacts["aligned.png"]["sha256"]
            sam_path = root / "bridge" / f"{sample_id}-sam" / "report.json"
            sam = sam_report(sam_path, aligned_hash, [20, 45, 70])
            sample.update(
                sam_report=sam_path.relative_to(root).as_posix(),
                sam_input_sha256=aligned_hash,
                sam_runs=sam["runs"],
            )
        write_json(case_path, case_report)
        samples.append(sample)
    bridge = {
        "samples": samples,
        "sam_checkpoint_sha256": checkpoint,
        "inputs": 3,
        "alignment_successes": 2,
        "sam_images": 6,
    }
    bridge_path = root / "bridge" / "report.json"
    write_json(bridge_path, bridge)

    def build():
        return protocol.build_manifest(root, config_path, subset, bridge_path, controls)

    def generate_control():
        return sam_report(controls / "known" / "report.json", samples[0]["sam_input_sha256"], [27])

    return SimpleNamespace(
        root=root,
        config=config,
        config_path=config_path,
        subset=subset,
        rows=rows,
        save_csv=save_csv,
        bridge=bridge,
        bridge_path=bridge_path,
        samples=samples,
        controls=controls,
        build=build,
        generate_control=generate_control,
    )


def test_identity_assignment_is_deterministic_and_viewed_identities_are_development(evidence):
    first = evidence.build()
    evidence.rows.reverse()
    evidence.save_csv()
    second = evidence.build()
    assert first["identities"] == second["identities"]
    assert first["adult_images"] == second["adult_images"]
    assert {
        row["group"] for row in first["adult_images"] if row["subject_id"] in {"001", "002"}
    } == {"development"}
    assert first["summary"]["identity_groups"] == {
        "development": 2,
        "calibration_research": 1,
        "evaluation_research_holdout": 1,
    }
    assert all(row["historical_preprocessing_exposed"] for row in first["identities"])
    assert not first["independent_external_evaluation"]
    assert not first["independent_landmark_nme_evaluation"]


def test_unknown_source_stays_null_and_source_failure_is_retained(evidence):
    result = evidence.build()
    unknown = next(case for case in result["bridge_cases"] if case["sample_id"] == "unknown")
    assert unknown["source_age"]["value"] is None
    assert unknown["source_age"]["method"] == "unknown"
    assert unknown["same_age_control"] == {
        "status": "not_applicable_unknown_source_age",
        "target_age": None,
    }
    failed = next(case for case in result["bridge_cases"] if case["sample_id"] == "failure")
    assert failed["error_code"] == "NO_FACE"
    assert failed["same_age_control"]["status"] == "blocked_source_failure"
    assert len(result["bridge_cases"]) == 3
    assert not result["summary"]["same_age_controls_complete"]


def test_exact_generated_control_completes_snapshot(evidence):
    evidence.generate_control()
    result = evidence.build()
    control = result["bridge_cases"][0]["same_age_control"]
    assert control["status"] == "generated" and control["target_age"] == 27
    assert result["summary"]["same_age_controls_complete"]
    assert not result["g3_complete"] and not result["training_use"]


def test_existing_exact_target_is_reused(evidence):
    for row in evidence.rows:
        if row["subject_id"] == "001":
            original = evidence.subset.parent / row["image"]
            moved = original.with_name("001A45.JPG")
            original.rename(moved)
            row.update(age=45, image="images/001A45.JPG")
            evidence.samples[0].update(age=45, path=moved.relative_to(evidence.root).as_posix())
    evidence.save_csv()
    write_json(evidence.bridge_path, evidence.bridge)
    control = evidence.build()["bridge_cases"][0]["same_age_control"]
    assert control["status"] == "reused_existing" and control["target_age"] == 45


@pytest.mark.parametrize("value", [27.5, 45, True])
def test_source_age_metadata_cannot_be_rounded_or_replaced(evidence, value):
    evidence.samples[0]["age"] = value
    write_json(evidence.bridge_path, evidence.bridge)
    with pytest.raises(ValueError, match="identity/age"):
        evidence.build()


def test_unknown_external_age_cannot_receive_a_default(evidence):
    evidence.samples[2]["age"] = 45
    write_json(evidence.bridge_path, evidence.bridge)
    with pytest.raises(ValueError, match="unknown/null"):
        evidence.build()


def test_source_hash_tampering_is_rejected(evidence):
    image = evidence.subset.parent / evidence.rows[0]["image"]
    image.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        evidence.build()


def test_same_age_output_tampering_is_rejected(evidence):
    evidence.generate_control()
    (evidence.controls / "known" / "age-27.png").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        evidence.build()


def test_same_age_report_cannot_substitute_another_integer_condition(evidence):
    report = evidence.generate_control()
    report["runs"][0]["target_age"] = 28
    write_json(evidence.controls / "known" / "report.json", report)
    with pytest.raises(ValueError, match="exact source label"):
        evidence.build()


def test_existing_target_output_tampering_is_rejected(evidence):
    sample = evidence.samples[0]
    report_dir = (evidence.root / sample["sam_report"]).parent
    (report_dir / sample["sam_runs"][0]["output"]).write_bytes(b"changed target image")
    with pytest.raises(ValueError, match="SHA-256"):
        evidence.build()


def test_declared_source_size_must_match_actual_bytes(evidence):
    evidence.rows[0]["size_bytes"] += 1
    evidence.save_csv()
    with pytest.raises(ValueError, match="File size"):
        evidence.build()


def test_coverage_counts_distinct_ages_and_keeps_age70_boundary():
    rows = [
        {"subject_id": "001", "source_age": 20, "group": "development"},
        {"subject_id": "001", "source_age": 20, "group": "development"},
        {"subject_id": "002", "source_age": 69, "group": "evaluation_research_holdout"},
        {"subject_id": "002", "source_age": 70, "group": "evaluation_research_holdout"},
    ]
    result = protocol._coverage(rows, {"001": "development", "002": "evaluation_research_holdout"})
    assert result["age_strata"]["all"]["20-29"] == {"images": 2, "identities": 1}
    assert result["age_strata"]["all"]["60-69"] == {"images": 1, "identities": 1}
    assert result["age_strata"]["all"]["70"] == {"images": 1, "identities": 1}
    assert result["distinct_age_pair_eligible_identities"] == {
        "all": 1,
        "development": 0,
        "evaluation_research_holdout": 1,
    }


def test_optional_provenance_reports_are_hash_bound(evidence):
    dataset = evidence.subset.parent / "manifest.json"
    pipeline = evidence.root / "output/research/fgnet-pipeline-20261020/report.json"
    write_json(dataset, {"research_only": True})
    write_json(pipeline, {"training_use": False})
    inputs = evidence.build()["inputs"]
    assert inputs["dataset_manifest"]["sha256"] == digest(dataset.read_bytes())
    assert inputs["historical_pipeline_report"]["sha256"] == digest(pipeline.read_bytes())


@pytest.mark.parametrize("section", ["input", "checkpoint"])
def test_control_input_and_model_must_match_original_evidence(evidence, section):
    report = evidence.generate_control()
    report[section]["sha256"] = "0" * 64
    write_json(evidence.controls / "known" / "report.json", report)
    with pytest.raises(ValueError, match="SAM input/checkpoint"):
        evidence.build()


def test_cross_group_duplicate_bytes_are_rejected(evidence):
    first, other = evidence.rows[0], evidence.rows[2]
    (evidence.subset.parent / other["image"]).write_bytes(
        (evidence.subset.parent / first["image"]).read_bytes()
    )
    other.update(sha256=first["sha256"], size_bytes=first["size_bytes"])
    evidence.save_csv()
    with pytest.raises(ValueError, match="across identity-use groups"):
        evidence.build()


def test_viewed_identity_cannot_move_to_holdout(evidence):
    evidence.config["grouping"]["development_subject_ids"] = ["002"]
    write_json(evidence.config_path, evidence.config)
    with pytest.raises(ValueError, match="development CSV"):
        evidence.build()


def test_csv_path_escape_is_rejected(evidence):
    evidence.rows[0]["image"] = "../../outside/001A27.JPG"
    evidence.save_csv()
    with pytest.raises(ValueError, match="workspace root"):
        evidence.build()


def test_missing_bridge_case_cannot_produce_complete_controls(evidence):
    evidence.bridge["samples"].pop()
    write_json(evidence.bridge_path, evidence.bridge)
    with pytest.raises(ValueError, match="sample count"):
        evidence.build()


def arguments(evidence, output):
    return [
        "--root",
        str(evidence.root),
        "--protocol",
        str(evidence.config_path),
        "--subset",
        str(evidence.subset),
        "--bridge-report",
        str(evidence.bridge_path),
        "--controls-dir",
        str(evidence.controls),
        "--output-dir",
        str(output),
    ]


def test_required_controls_fail_without_publishing_partial_snapshot(evidence):
    output = evidence.root / "snapshot"
    assert protocol.main([*arguments(evidence, output), "--require-controls"]) == 1
    assert not output.exists()
    evidence.generate_control()
    assert protocol.main([*arguments(evidence, output), "--require-controls"]) == 0
    assert {path.name for path in output.iterdir()} == {"manifest.json", "summary.json"}


def test_existing_output_is_preserved_before_evidence_reads(evidence):
    output = evidence.root / "snapshot"
    output.mkdir()
    sentinel = output / "manifest.json"
    sentinel.write_bytes(b"prior evidence")
    evidence.subset.unlink()
    assert protocol.main(arguments(evidence, output)) == 1
    assert sentinel.read_bytes() == b"prior evidence"


def freeze(evidence):
    frozen = {
        "protocol_id": evidence.config["protocol_id"],
        "identity_groups": {
            row["subject_id"]: row["group"] for row in evidence.build()["identities"]
        },
        "inputs": {
            path.relative_to(evidence.root).as_posix(): digest(path.read_bytes())
            for path in (evidence.config_path, evidence.subset, evidence.bridge_path)
        },
    }
    path = evidence.root / "freeze.json"
    write_json(path, frozen)
    return path, frozen


def test_changed_protocol_is_rejected_against_pre_inference_freeze(evidence):
    path, _ = freeze(evidence)
    evidence.config["grouping"]["seed"] = "changed-after-inference"
    write_json(evidence.config_path, evidence.config)
    output = evidence.root / "snapshot"
    assert protocol.main([*arguments(evidence, output), "--frozen-inputs", str(path)]) == 1
    assert not output.exists()


def test_frozen_identity_assignments_are_verified_and_baseline_is_bound(evidence):
    path, frozen = freeze(evidence)
    output = evidence.root / "snapshot"
    assert protocol.main([*arguments(evidence, output), "--frozen-inputs", str(path)]) == 0
    result = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert result["inputs"]["pre_inference_freeze"]["sha256"] == digest(path.read_bytes())
    frozen["identity_groups"]["003"] = "development"
    write_json(path, frozen)
    second = evidence.root / "second-snapshot"
    assert protocol.main([*arguments(evidence, second), "--frozen-inputs", str(path)]) == 1
    assert not second.exists()

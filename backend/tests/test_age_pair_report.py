"""Synthetic cross-study geometry checks, not age/identity model acceptance."""

import hashlib
import importlib.util
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools" / "age_pair_report.py"
_SPEC = importlib.util.spec_from_file_location("age_pair_report", _PATH)
report = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(report)


@pytest.fixture
def study(tmp_path):
    def pin(path):
        raw = path.read_bytes()
        return {
            "path": path.relative_to(tmp_path).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }

    def image(name):
        path = tmp_path / name
        path.write_bytes(name.encode())
        return pin(path)

    source, target, near = image("003A38.JPG"), image("003A20.JPG"), image("003A21.JPG")
    same, generated = image("sam-038.png"), image("sam-020.png")
    case = {
        "sample_id": "fgnet-003a38",
        "subject_id": "003",
        "group": "development",
        "source_age": {"value": 38},
        "source_status": "passed",
        "source": source,
        "target_runs": [dict(target_age=20, **generated), dict(target_age=70, **generated)],
        "same_age_control": {"output": same},
    }
    manifest = {
        "bridge_cases": [case],
        "adult_images": [
            dict(subject_id="003", source_age=age, group="development", **item)
            for age, item in [(38, source), (20, target), (21, near)]
        ],
    }
    vertices = np.array([[0.0, -1, 0], [0, 1, 0], [1, 0, 1], [0, 0, 0.5]])

    def fit(sample_id, image_pin, shift, directory):
        path = tmp_path / f"{directory}-{sample_id}.npz"
        full = vertices + [shift, 0, 0]
        np.savez(path, vertices=full, neutral_vertices=full, projection=np.eye(3, 4))
        return {
            "sample_id": sample_id,
            "subject_id": "003",
            "input": image_pin,
            "status": "ok",
            "error_code": None,
            "topology_sha256": "a" * 64,
            "fit_artifact": pin(path),
        }

    models = {role: {"manifest_sha256": "b" * 64} for role in ("detector", "reconstructor")}
    real = {
        "study": "longitudinal",
        "models": deepcopy(models),
        "fit_records": [
            fit("fgnet-003a38", source, 0, "real"),
            fit("fgnet-003a20", target, 1, "real"),
        ],
    }
    sam = {
        "study": "generated",
        "models": deepcopy(models),
        "fit_records": [
            fit("fgnet-003a38", source, 0, "sam"),
            fit("fgnet-003a38--sam-038", same, 0.4, "sam"),
            fit("fgnet-003a38--sam-020", generated, 1.4, "sam"),
        ],
    }
    return SimpleNamespace(
        root=tmp_path, manifest=manifest, real=real, sam=sam, pin=pin, vertices=vertices
    )


def test_exact_target_matching_keeps_fixed_source_units_and_same_age_drift(study):
    records, views = report.matched_comparisons(study.root, study.manifest, study.real, study.sam)
    assert len(records) == len(views) == 1  # age21 is not substituted; no real70 exists
    row = records[0]
    assert row["real_target_id"] == "fgnet-003a20" and row["target_age"] == 20
    assert row["same_age_drift_rms"] == pytest.approx(0.2)
    assert row["generated_to_real_neutral_rms"] == pytest.approx(0.2)
    assert row["real_increment_rms"] == pytest.approx(0.5)
    assert row["generated_increment_rms"] == pytest.approx(0.5)
    assert row["increment_residual_rms"] == pytest.approx(0, abs=1e-12)
    assert row["source_frame"]["source_to_canonical_uniform_scale"] == 0.5


def test_failed_fit_is_retained_as_a_failed_exact_match(study):
    study.sam["fit_records"][-1].update(status="failed", error_code="NO_FACE")
    records, views = report.matched_comparisons(study.root, study.manifest, study.real, study.sam)
    assert records[0]["status"] == "failed" and not views
    assert "NO_FACE" in records[0]["constituent_errors"]


def test_model_or_basis_version_mismatch_cannot_be_compared(study):
    study.sam["models"]["reconstructor"]["manifest_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="model and basis"):
        report.matched_comparisons(study.root, study.manifest, study.real, study.sam)


@pytest.mark.parametrize("field,value", [("subject_id", "004"), ("topology_sha256", "c" * 64)])
def test_identity_or_topology_mismatch_is_rejected(study, field, value):
    study.sam["fit_records"][-1][field] = value
    with pytest.raises(ValueError, match="identity|topology"):
        report.matched_comparisons(study.root, study.manifest, study.real, study.sam)


def test_fit_and_input_tampering_are_rejected(study):
    path = study.root / study.sam["fit_records"][-1]["fit_artifact"]["path"]
    path.write_bytes(b"tampered fitted geometry")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        report.matched_comparisons(study.root, study.manifest, study.real, study.sam)


def test_two_studies_must_reproduce_the_same_original_fit(study):
    item = study.sam["fit_records"][0]
    path = study.root / item["fit_artifact"]["path"]
    np.savez(
        path,
        vertices=study.vertices + 0.1,
        neutral_vertices=study.vertices + 0.1,
        projection=np.eye(3, 4),
    )
    item["fit_artifact"] = study.pin(path)
    with pytest.raises(ValueError, match="different source fits"):
        report.matched_comparisons(study.root, study.manifest, study.real, study.sam)


def test_non_development_identity_and_swapped_studies_are_rejected(study):
    study.manifest["bridge_cases"][0]["group"] = "evaluation_research_holdout"
    with pytest.raises(ValueError, match="non-development"):
        report.matched_comparisons(study.root, study.manifest, study.real, study.sam)
    with pytest.raises(ValueError, match="in that order"):
        report.matched_comparisons(study.root, study.manifest, study.sam, study.real)


def test_existing_report_directory_is_not_modified(tmp_path):
    marker = tmp_path / "marker"
    marker.write_text("keep", encoding="utf-8")
    assert (
        report.main(
            [
                "--root",
                str(tmp_path),
                "--protocol-manifest",
                "missing",
                "--longitudinal-report",
                "missing",
                "--generated-report",
                "missing",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 1
    )
    assert marker.read_text(encoding="utf-8") == "keep"

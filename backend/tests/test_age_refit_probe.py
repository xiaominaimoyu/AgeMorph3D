"""Synthetic offline orchestration checks; no real-model quality acceptance."""

import csv
import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from agemorph3d.model_assets import ModelAssetError
from agemorph3d.tddfa import TddfaResult
from PIL import Image

_PATH = Path(__file__).resolve().parents[2] / "tools/age_refit_probe.py"
_SPEC = importlib.util.spec_from_file_location("age_refit_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)
_VERIFIED_PROTOCOL = probe._verified_protocol


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def example(tmp_path, monkeypatch):
    points = np.column_stack(
        (np.linspace(-2, 2, 68), np.linspace(-3, 3, 68), np.sin(np.arange(68)))
    ).astype(np.float32)
    triangles = np.array([[0, 1, 2], [1, 2, 3]], dtype=np.int64)
    raw = TddfaResult(
        shape=np.zeros(40, dtype=np.float32),
        expr=np.zeros(10, dtype=np.float32),
        vertices=points,
        triangles=triangles,
        projection=np.column_stack((np.eye(3), np.zeros(3))).astype(np.float32),
        roi=(0, 0, 120, 120),
        topology_sha256="a" * 64,
    )
    calls, closed = [], []
    state = SimpleNamespace(raw=raw)

    def image(name, value):
        path = tmp_path / "images" / name
        path.parent.mkdir(exist_ok=True)
        Image.fromarray(np.full((32, 32, 3), value, dtype=np.uint8)).save(path)
        data = path.read_bytes()
        return {
            "path": path.relative_to(tmp_path).as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }

    source = image("001A20.png", 20)
    target = image("001A30.png", 30)
    failed = image("001A40.png", 0)
    heldout = image("002A30.png", 50)
    manifest = {
        "protocol_id": "synthetic-stage2",
        "bridge_cases": [],
        "adult_images": [
            dict(pin, subject_id=subject, source_age=age, group=group)
            for pin, subject, age, group in (
                (source, "001", 20, "development"),
                (target, "001", 30, "development"),
                (failed, "001", 40, "development"),
                (heldout, "002", 30, "evaluation_research_holdout"),
            )
        ],
    }

    def detect(rgb):
        marker = int(rgb[0, 0, 0])
        calls.append(marker)
        if marker == 0:
            return []
        return [SimpleNamespace(bbox=(0, 0, 32, 32), confidence=0.9)]

    detector = SimpleNamespace(detect=detect, close=lambda: closed.append("detector"))
    reconstructor = SimpleNamespace(
        reconstruct=lambda rgb, bbox: replace(
            state.raw, vertices=state.raw.vertices + float(rgb[0, 0, 0]) * 0.01
        ),
        keypoint_coordinates=np.arange(204).reshape(68, 3),
        topology_sha256=raw.topology_sha256,
        triangles=triangles,
        close=lambda: closed.append("reconstructor"),
    )

    def models(args, original_manifest, report, owned):
        owned.update(detector=detector, reconstructor=reconstructor)
        return np.zeros((204, 10))

    monkeypatch.setattr(probe, "_load_models", models)
    monkeypatch.setattr(probe, "_verified_protocol", lambda root, path, freeze: manifest)
    protocol_path, freeze = tmp_path / "manifest.json", tmp_path / "freeze.json"
    write_json(protocol_path, manifest)
    write_json(freeze, {"synthetic": True})
    output = tmp_path / "result"
    arguments = [
        "--root",
        str(tmp_path),
        "--study",
        "longitudinal",
        "--protocol-manifest",
        str(protocol_path),
        "--frozen-inputs",
        str(freeze),
        "--output-dir",
        str(output),
        "--research-allow-unresolved",
    ]
    return SimpleNamespace(
        root=tmp_path,
        manifest=manifest,
        raw=raw,
        state=state,
        image=image,
        detector=detector,
        reconstructor=reconstructor,
        calls=calls,
        closed=closed,
        arguments=arguments,
        output=output,
        protocol_path=protocol_path,
        freeze=freeze,
    )


def report(example):
    return json.loads((example.output / "report.json").read_text(encoding="utf-8"))


def test_longitudinal_keeps_all_pairs_failures_and_development_scope(example):
    assert probe.main(example.arguments) == 0
    result = report(example)
    assert result["summary"]["requested_images"] == 3
    assert result["summary"]["fit_statuses"] == {"ok": 2, "failed": 1}
    assert result["summary"]["failures"] == {"NO_FACE": 1}
    assert len(result["comparison_records"]) == 6
    assert sum(row["status"] == "ok" for row in result["comparison_records"]) == 2
    assert 50 not in example.calls
    assert example.closed == ["detector", "reconstructor"]
    assert result["model_ownership_released"]
    assert all(
        not result[key]
        for key in (
            "g3_complete",
            "service_ready",
            "years_calibrated",
            "identity_accepted",
            "training_use",
            "uv_registered",
        )
    )
    successful = next(row for row in result["fit_records"] if row["status"] == "ok")
    assert np.array(successful["projection"]).shape == (3, 4)
    assert np.array(successful["projected_landmarks"]).shape == (68, 3)
    with np.load(example.root / successful["fit_artifact"]["path"], allow_pickle=False) as fit:
        assert set(fit.files) == {
            "vertices",
            "neutral_vertices",
            "shape",
            "expr",
            "projection",
            "roi",
        }
    for row in result["comparison_records"]:
        if row["status"] == "ok":
            source = next(x for x in result["fit_records"] if x["sample_id"] == row["source_id"])
            assert row["source_frame"] == source["canonical_frame"]
    for name, expected in (("fits.csv", 3), ("comparisons.csv", 6)):
        with (example.output / name).open(encoding="utf-8", newline="") as stream:
            assert len(list(csv.DictReader(stream))) == expected


def generated_case(example, sample_id, source_age):
    source = example.image(sample_id + "-original.png", 20)
    aligned = example.image(sample_id + "-aligned.png", 30)
    runs = [
        dict(example.image(f"{sample_id}-target-{age}.png", age), target_age=age)
        for age in (20, 45, 70)
    ]
    same = (
        {"status": "not_applicable_unknown_source_age", "target_age": None}
        if source_age is None
        else {"status": "reused_existing", "target_age": 45, "output": runs[1]}
    )
    return {
        "sample_id": sample_id,
        "subject_id": "external:" + sample_id if source_age is None else "001",
        "source_age": {"value": source_age},
        "source": source,
        "source_status": "passed",
        "same_age_control": same,
        "artifacts": {"aligned.png": aligned},
        "target_runs": runs,
    }


def test_generated_controls_deduplicate_reuse_and_preserve_unknown_age(example):
    example.manifest["bridge_cases"] = [
        generated_case(example, "known", 45),
        generated_case(example, "unknown", None),
    ]
    args = ["generated" if arg == "longitudinal" else arg for arg in example.arguments]
    assert probe.main(args) == 0
    result = report(example)
    assert result["summary"]["requested_images"] == 10
    assert result["summary"]["images_by_role"] == {
        "original": 2,
        "aligned_source": 2,
        "sam_generated": 6,
    }
    unknown = [row for row in result["fit_records"] if row["sample_id"].startswith("unknown")]
    assert len(unknown) == 5 and all(row["source_age"] is None for row in unknown)
    assert not any(row.get("is_same_age") for row in unknown)
    assert not any(
        row["kind"] == "source_vs_same_age" and row["source_id"] == "unknown"
        for row in result["comparison_records"]
    )
    fixed = next(
        row["canonical_frame"] for row in result["fit_records"] if row["sample_id"] == "known"
    )
    assert all(
        row["source_frame"] == fixed
        for row in result["comparison_records"]
        if row["reference_source_id"] == "known"
    )
    assert all(
        row["source_canonical_frame"] == fixed
        for row in result["fit_records"]
        if row.get("reference_source_id") == "known"
    )
    assert all(
        "canonical_frame" not in row for row in result["fit_records"] if row["role"] != "original"
    )


def test_generated_case_original_failure_is_not_discarded(example):
    case = generated_case(example, "negative", 45)
    case.update(source_status="failed", source=example.image("negative.png", 0))
    example.manifest["bridge_cases"] = [case]
    jobs = probe._jobs(example.manifest, "generated")
    assert len(jobs) == 1 and jobs[0]["role"] == "original"


def test_existing_directory_rejected_before_reading_or_loading(example, monkeypatch):
    example.output.mkdir()
    marker = example.output / "marker.txt"
    marker.write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(probe, "_verified_protocol", lambda *args: pytest.fail("must not read"))
    assert probe.main(example.arguments) == 1
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert not example.calls and not example.closed


def test_frozen_protocol_error_stops_before_output_and_model_load(example, monkeypatch):
    def invalid(*args):
        raise ValueError("synthetic changed protocol")

    monkeypatch.setattr(probe, "_verified_protocol", invalid)
    assert probe.main(example.arguments) == 1
    assert not example.output.exists() and not example.calls


def test_second_model_failure_disposes_first_owned_model(example, monkeypatch):
    def models(args, original_manifest, result, owned):
        owned["detector"] = example.detector
        raise ModelAssetError("private asset location must not leak")

    monkeypatch.setattr(probe, "_load_models", models)
    assert probe.main(example.arguments) == 1
    assert example.closed == ["detector"]
    result = report(example)
    assert result["model_ownership_released"] and result["error_code"] == "MODEL_ASSET_ERROR"
    assert "private" not in json.dumps(result)


def test_tampered_input_is_retained_as_failed_fit_without_inference(example):
    job = probe._jobs(example.manifest, "longitudinal")[0]
    (example.root / job["input"]["path"]).write_bytes(b"tampered")
    example.output.mkdir()
    (example.output / "fits").mkdir()
    record, raw = probe._fit_one(
        example.root,
        job,
        {"detector": example.detector, "reconstructor": example.reconstructor},
        np.zeros((204, 10)),
        example.output,
    )
    assert raw is None and record["status"] == "failed"
    assert record["error_code"] == "HASH_MISMATCH" and not example.calls


def test_native_inference_error_retains_every_requested_case(example):
    def native_failure(rgb, bbox):
        raise RuntimeError("private native model location")

    example.reconstructor.reconstruct = native_failure
    assert probe.main(example.arguments) == 0
    result = report(example)
    assert len(result["fit_records"]) == 3 and len(result["comparison_records"]) == 6
    assert result["summary"]["fit_statuses"] == {"failed": 3}
    assert "private" not in json.dumps(result)
    assert example.closed == ["detector", "reconstructor"]


def test_invalid_rotation_is_recorded_as_pose_failure(example):
    projection = example.raw.projection.copy()
    projection[0, 0] = -1
    example.state.raw = replace(example.raw, projection=projection)
    assert probe.main(example.arguments) == 0
    result = report(example)
    assert result["summary"]["failures"] == {"POSE_OR_EXPRESSION_INVALID": 2, "NO_FACE": 1}


def test_ordered_topology_failure_is_retained(example):
    example.state.raw = replace(example.raw, triangles=example.raw.triangles[::-1].copy())
    assert probe.main(example.arguments) == 0
    result = report(example)
    assert result["summary"]["fit_statuses"] == {"failed": 3}
    assert result["summary"]["failures"] == {"MODEL_OR_TOPOLOGY_MISMATCH": 2, "NO_FACE": 1}
    assert len(result["comparison_records"]) == 6


def test_protocol_snapshot_must_exactly_match_rebuilt_freeze(example, monkeypatch):
    saved = {
        "inputs": {
            "protocol": {"path": "protocol.json"},
            "adult_subset": {"path": "adult.csv"},
            "bridge_report": {"path": "bridge.json"},
        },
        "bridge_cases": [],
        "summary": {"same_age_controls_complete": True},
    }
    write_json(example.protocol_path, saved)
    monkeypatch.setattr(probe, "build_manifest", lambda *args: dict(saved, changed=True))
    with pytest.raises(ValueError, match="differs"):
        _VERIFIED_PROTOCOL(example.root, example.protocol_path, example.freeze)


def test_duplicate_fit_identifiers_are_rejected(example):
    example.manifest["adult_images"].append(dict(example.manifest["adult_images"][0]))
    with pytest.raises(ValueError, match="safe and unique"):
        probe._jobs(example.manifest, "longitudinal")

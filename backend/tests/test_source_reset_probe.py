"""Synthetic source-frame, immutable reset and offline evidence-boundary checks."""

import hashlib
import importlib.util
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

_PATH = Path(__file__).resolve().parents[2] / "tools/source_reset_probe.py"
_SPEC = importlib.util.spec_from_file_location("source_reset_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def case(tmp_path):
    root = tmp_path
    for name in probe._CODE:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# synthetic source pin\n", encoding="utf-8")
    paths = {
        key: root / value
        for key, value in {
            "study_plan": "plan.json",
            "protocol_manifest": "manifest.json",
            "generated_report": "generated.json",
            "bfm": "bfm.npz",
            "uv": "uv.npz",
        }.items()
    }
    vertices = np.array([[2, 115, 0], [10, 115, 0], [2, 107, 0]], dtype=np.float32)
    triangles = np.array([[0, 1, 2]], dtype=np.int64)
    keypoints = np.arange(9, dtype=np.int64).reshape(3, 3)
    digest = hashlib.sha256(b"agemorph3d:tddfa-topology:v2\0")
    for array in (np.array([3, 1], dtype="<i8"), triangles.astype("<i8"), keypoints.astype("<i8")):
        digest.update(array.tobytes(order="C"))
    topology_hash = digest.hexdigest()
    np.savez_compressed(paths["bfm"], w_exp=np.zeros((9, 10)), tri=triangles, keypoints=keypoints)
    np.savez_compressed(
        paths["uv"],
        uv=np.array([[0, 1], [1, 1], [0, 0]], dtype=np.float32),
        topology_sha256=topology_hash,
    )
    topology = root / "topology.npz"
    np.savez_compressed(topology, triangles=triangles, keypoint_coordinates=keypoints)
    yy, xx = np.mgrid[:16, :16]
    rgb = np.stack((xx * 10, yy * 10, xx * 3 + yy), axis=-1).astype(np.uint8)
    sources, records = [], []
    files = [topology]
    for sample_id, age in (("known", 27), ("fractional", 42.5), ("unknown", None)):
        image_path = root / f"{sample_id}.png"
        Image.fromarray(rgb).save(image_path)
        fit_path = root / f"{sample_id}.npz"
        shape = np.arange(40, dtype=np.float32)
        np.savez_compressed(
            fit_path,
            vertices=vertices,
            neutral_vertices=vertices.astype(np.float64),
            shape=shape,
            expr=np.zeros(10),
            projection=np.eye(3, 4),
            roi=np.array([0, 0, 120, 120]),
        )
        source_pin = probe._pin(root, image_path)
        sources.append(
            {
                "sample_id": sample_id,
                "subject_id": sample_id,
                "group": "development",
                "source": source_pin,
                "source_age": {
                    "value": age,
                    "method": "dataset_filename" if age is not None else "unknown",
                    "independently_verified": False,
                },
                "source_status": "passed",
            }
        )
        records.append(
            {
                "sample_id": sample_id,
                "subject_id": sample_id,
                "reference_source_id": sample_id,
                "source_age": age,
                "role": "original",
                "input": source_pin,
                "status": "ok",
                "topology_sha256": topology_hash,
                "image_size": [16, 16],
                "fit_artifact": probe._pin(root, fit_path),
                "canonical_frame": probe.source_frame(vertices),
            }
        )
        files.extend([image_path, fit_path])
    records.append(
        {"sample_id": "old-failed", "role": "original", "status": "failed", "error_code": "NO_FACE"}
    )
    manifest = {"protocol_id": "synthetic-n0", "bridge_cases": sources}
    generated = {
        "study": "generated",
        "inputs": {},
        "expression_basis": {},
        "fit_records": records,
        "topology_artifact": probe._pin(root, topology),
    }
    plan = {
        "protocol_id": probe.PROTOCOL_ID,
        "atlas_size": 4,
        "expected_sources": 3,
        "expected_known_sources": 2,
        "source_ids": [row["sample_id"] for row in sources],
        "inputs": {},
    }

    def repin():
        write_json(paths["protocol_manifest"], manifest)
        generated["inputs"]["protocol_manifest"] = probe._pin(root, paths["protocol_manifest"])
        generated["expression_basis"]["asset"] = probe._pin(root, paths["bfm"])
        write_json(paths["generated_report"], generated)
        all_files = files + [p for key, p in paths.items() if key != "study_plan"]
        all_files += [root / name for name in probe._CODE]
        plan["inputs"] = {
            path.relative_to(root).as_posix(): {
                key: value for key, value in probe._pin(root, path).items() if key != "path"
            }
            for path in all_files
        }
        write_json(paths["study_plan"], plan)

    repin()
    args = SimpleNamespace(root=root, output_dir=root / "new-output", atlas_size=4, **paths)
    return SimpleNamespace(
        root=root,
        paths=paths,
        args=args,
        manifest=manifest,
        generated=generated,
        plan=plan,
        repin=repin,
        rgb=rgb,
    )


def test_real_asset_path_and_fractional_offline_reset_leave_api_age_unknown(case):
    report = probe.run(case.args)
    assert report["summary"]["assets_created"] == 3
    assert report["summary"]["known_label_resets_passed"] == 2
    assert report["summary"]["unknown_age_rejected"] == 1
    assert report["summary"]["failed_sources"] == 0
    assert report["source_age_api_policy"] == "unknown"
    assert report["research_only"] and not report["service_ready"] and not report["g3_complete"]
    assert not report["production_source_reset_accepted"]
    assert not report["rendered_continuity_accepted"]
    assert report["retained_prior_original_fit_failures"][0]["error_code"] == "NO_FACE"
    for row in report["records"]:
        assert row["source_age"] == probe.UNKNOWN_AGE
        assert row["glb_roundtrip"] == {
            "arrays_exact": True,
            "embedded_png_exact": True,
            "rgba_exact": True,
        }
        data = probe._path(case.root, row["artifacts"]["glb"]["path"]).read_bytes()
        size = struct.unpack_from("<I", data, 12)[0]
        document = json.loads(data[20 : 20 + size])
        assert document["extras"]["source_age"] == probe.UNKNOWN_AGE
        assert not document["extras"]["base_texture"]["age_generated"]
        if row["label_source_age"] is None:
            assert row["reset_status"] == "source_age_unknown"
            assert all(value is None for value in row["byte_equality"].values())
        else:
            assert row["reset_status"] == "passed"
            assert all(row["byte_equality"].values())
            assert row["reset"]["target_research_label"] == row["label_source_age"]
    fractional = next(row for row in report["records"] if row["sample_id"] == "fractional")
    assert fractional["label_source_age"] == 42.5


@pytest.mark.parametrize(
    "name", ["known.png", "known.npz", "uv.npz", "tools/source_reset_probe.py"]
)
def test_input_or_implementation_drift_rejected_before_output(case, name):
    with (case.root / name).open("ab") as stream:
        stream.write(b"drift")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        probe.run(case.args)
    assert not case.args.output_dir.exists()


def test_missing_input_binding_rejected_before_output(case):
    del case.plan["inputs"]["known.npz"]
    write_json(case.paths["study_plan"], case.plan)
    with pytest.raises(ValueError, match="pins must be in the frozen plan"):
        probe.run(case.args)
    assert not case.args.output_dir.exists()


@pytest.mark.parametrize(
    "change", ["group", "api_age", "source_input", "source_frame", "cohort", "duplicate_fit"]
)
def test_frozen_source_association_and_research_boundary_rejected(case, change):
    if change == "group":
        case.manifest["bridge_cases"][0]["group"] = "evaluation_research_holdout"
    elif change == "api_age":
        case.manifest["bridge_cases"][0]["source_age"]["method"] = "user"
    elif change == "source_input":
        case.generated["fit_records"][0]["input"] = case.manifest["bridge_cases"][1]["source"]
    elif change == "source_frame":
        case.generated["fit_records"][0]["canonical_frame"]["source_center"][0] += 1
    elif change == "cohort":
        case.plan["source_ids"].reverse()
    else:
        case.generated["fit_records"].append(case.generated["fit_records"][0])
    case.repin()
    with pytest.raises(ValueError):
        probe.run(case.args)
    assert not case.args.output_dir.exists()


def test_wrong_uv_topology_fails_even_when_rehashed(case):
    np.savez_compressed(
        case.paths["uv"], uv=np.zeros((3, 2), dtype=np.float32), topology_sha256="ff" * 32
    )
    case.repin()
    with pytest.raises(ValueError, match="exact original vertex order"):
        probe.run(case.args)
    assert not case.args.output_dir.exists()


def test_existing_output_is_preserved(case):
    case.args.output_dir.mkdir()
    sentinel = case.args.output_dir / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError, match="must not already exist"):
        probe.run(case.args)
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_one_bad_photo_frame_is_retained_without_dropping_other_sources(case):
    case.generated["fit_records"][0]["image_size"] = [15, 16]
    case.repin()
    report = probe.run(case.args)
    assert report["summary"]["failed_sources"] == 1
    assert report["summary"]["assets_created"] == 2
    assert report["summary"]["known_label_resets_passed"] == 1
    assert report["records"][0]["status"] == "failed"
    assert report["records"][0]["reset_status"] == "failed"
    assert report["records"][0]["error_code"] == "SOURCE_ASSET_FAILED"
    assert not report["summary"]["all_known_offline_resets_passed"]
    assert not report["summary"]["all_requested_original_assets_built"]


def test_corrupt_reset_bytes_are_counted_as_failures(case, monkeypatch):
    original_reset = probe.static_fallback_at_age

    def corrupt_known(source, source_age, target_age):
        if source_age is None:
            return original_reset(source, source_age, target_age)
        return source._replace(png=b"changed original PNG")

    monkeypatch.setattr(probe, "static_fallback_at_age", corrupt_known)
    report = probe.run(case.args)
    assert report["summary"]["failed_sources"] == 2
    assert report["summary"]["known_label_resets_passed"] == 0
    assert report["summary"]["unknown_age_rejected"] == 1
    assert all(row["reset_status"] == "failed" for row in report["records"][:2])
    assert not report["summary"]["all_known_offline_resets_passed"]


def test_path_outside_workspace_is_rejected(case, capsys):
    assert (
        probe.main(
            ["--root", str(case.root), "--study-plan", "../escape.json", "--output-dir", "out"]
        )
        == 2
    )
    assert "within the selected workspace" in capsys.readouterr().err

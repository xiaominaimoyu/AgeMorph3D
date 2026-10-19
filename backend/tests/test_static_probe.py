"""Synthetic CLI checks establish privacy and research boundaries, not real G1."""

import hashlib
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from agemorph3d import static_probe
from agemorph3d.model_assets import ModelAssetError


@pytest.fixture
def arguments(tmp_path):
    for name in ("detector", "reconstructor"):
        (tmp_path / f"{name}.json").write_text("synthetic manifest")
    with Image.new("RGB", (12, 8), "white") as image:
        image.save(tmp_path / "private-original-name.png")
    return [
        "--detector-manifest",
        str(tmp_path / "detector.json"),
        "--reconstructor-manifest",
        str(tmp_path / "reconstructor.json"),
        "--image",
        str(tmp_path / "private-original-name.png"),
        "--output-dir",
        str(tmp_path / "output"),
    ]


@pytest.fixture
def synthetic(monkeypatch):
    np = pytest.importorskip("numpy")

    calls = []
    faces = [SimpleNamespace(bbox=(1, 1, 5, 5))]

    def verify(path, *, research_allow_unresolved=False):
        calls.append(research_allow_unresolved)
        if not research_allow_unresolved:
            raise ModelAssetError("private-original-name.png secret path")
        role = path.stem
        return SimpleNamespace(
            manifest=SimpleNamespace(
                model_id=f"synthetic-{role}",
                backend=static_probe._BACKENDS[role],
                revision="test",
            ),
            license_verified=False,
        )

    raw = SimpleNamespace(
        vertices=np.array([[-1, -1, 0], [0, 1, 0.2], [1, -1, 0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.uint32),
        shape=np.array([0.25], dtype=np.float32),
        expr=np.array([0.125], dtype=np.float32),
        projection=np.column_stack((np.eye(3), np.zeros(3))),
        roi=(0.0, 0.0, 12.0, 8.0),
        topology_sha256="a" * 64,
        coordinate_system="bfm_model_raw",
    )
    models = {
        "detector": SimpleNamespace(
            provider="CPUExecutionProvider", license_verified=False, detect=lambda _rgb: faces
        ),
        "reconstructor": SimpleNamespace(
            provider="CPUExecutionProvider",
            license_verified=False,
            reconstruct=lambda _rgb, _bbox: raw,
        ),
    }
    monkeypatch.setattr(static_probe, "load_verified_manifest", verify)
    monkeypatch.setattr(static_probe, "_construct_model", lambda role, _assets: models[role])
    # The synthetic triangle cannot satisfy the real 40/10/68-point operator contract.
    # These tests cover CLI orchestration; real operator checks are exercised by the real probe.
    monkeypatch.setattr(static_probe, "detector_selftest", lambda _model: None)
    monkeypatch.setattr(static_probe, "reconstructor_selftest", lambda _model: None)
    return SimpleNamespace(calls=calls, faces=faces)


def test_strict_requires_explicit_isolated_override(arguments, synthetic, tmp_path, capsys):
    assert static_probe.main(arguments) == 1
    report = json.loads((tmp_path / "output/report.json").read_text(encoding="utf-8"))
    assert report["error_code"] == "MODEL_ASSET_ERROR"
    assert report["license_verified"] is False
    assert "secret" not in json.dumps(report) and "private-original" not in json.dumps(report)
    arguments[-1] = str(tmp_path / "research")
    assert static_probe.main([*arguments, "--research-allow-unresolved"]) == 0
    assert synthetic.calls == [False, True, True]
    assert "secret" not in capsys.readouterr().out


def test_success_records_private_hashes_and_never_grants_readiness(arguments, synthetic, tmp_path):
    assert (
        static_probe.main([*arguments, "--research-allow-unresolved", "--source-age", "42.5"]) == 0
    )
    output = tmp_path / "output"
    text = (output / "report.json").read_text(encoding="utf-8")
    report = json.loads(text)
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    assert report["technical_execution"] == "passed"
    assert report["service_ready"] is False and report["g1_complete"] is False
    assert report["license_verified"] is False
    assert report["input"]["width"] == 12 and report["input"]["height"] == 8
    assert report["geometry"]["vertex_count"] == 3
    assert report["geometry"]["triangle_count"] == 1
    assert report["geometry"]["coordinate_metadata"]["canonical_unit"] == "dimensionless"
    assert (
        report["geometry"]["glb_sha256"]
        == hashlib.sha256((output / "mesh.glb").read_bytes()).hexdigest()
    )
    assert len(report["models"]["detector"]["manifest_sha256"]) == 64
    assert result["mesh_id"] == "offline_research" and result["asset_mode"] == "static"
    assert result["source_age"] == {"value": 42.5, "method": "user", "calibration_id": None}
    assert result["capabilities"] == {"age_morph": False, "age_texture": False}
    assert "private-original" not in text and str(tmp_path) not in text


@pytest.mark.parametrize(("count", "code"), [(0, "NO_FACE"), (2, "MULTI_FACE")])
def test_face_failures_leave_only_sanitized_report(arguments, synthetic, tmp_path, count, code):
    synthetic.faces[:] = [SimpleNamespace(bbox=(1, 1, 5, 5)) for _ in range(count)]
    assert static_probe.main([*arguments, "--research-allow-unresolved"]) == 1
    output = tmp_path / "output"
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["error_code"] == code and report["technical_execution"] == "failed"
    assert not (output / "mesh.glb").exists() and not (output / "result.json").exists()
    assert report["service_ready"] is False and report["g1_complete"] is False


def test_existing_outputs_are_preserved(arguments, synthetic, tmp_path, capsys):
    output = tmp_path / "output"
    output.mkdir()
    previous = b"a previous successful or private artifact"
    (output / "mesh.glb").write_bytes(previous)
    assert static_probe.main([*arguments, "--research-allow-unresolved"]) == 1
    assert (output / "mesh.glb").read_bytes() == previous
    assert "OUTPUT_EXISTS" in capsys.readouterr().out
    assert synthetic.calls == []


def test_import_does_not_load_optional_inference_dependencies():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import agemorph3d.static_probe; "
            "assert not {'numpy', 'cv2', 'onnxruntime'} & sys.modules.keys()",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

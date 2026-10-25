"""Synthetic CLI evidence and failure cleanup; no model, SAM or subprocess runs."""

import hashlib
import importlib.util
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools/research_aging_pipeline_probe.py"
_SPEC = importlib.util.spec_from_file_location("research_aging_pipeline_probe", _PATH)
probe = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(probe)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_file(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture(autouse=True)
def forbid_real_inference_or_subprocess(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("This CLI unit test cannot load real models or run a subprocess")

    monkeypatch.setattr(probe.subprocess, "run", forbidden)
    monkeypatch.setattr(probe, "_construct_model", forbidden)
    monkeypatch.setattr(probe, "load_verified_manifest", forbidden)
    monkeypatch.setattr(probe, "SamWorkerClient", forbidden)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-workspace"
    root.mkdir()
    image, uv = root / "data/source.jpg", root / "output/common-uv.npz"
    image.parent.mkdir()
    uv.parent.mkdir()
    image.write_bytes(b"synthetic source, never decoded")
    uv.write_bytes(b"synthetic UV, never decoded")
    monkeypatch.setattr(probe, "ROOT", root)
    monkeypatch.setattr(probe, "IMAGE", image)
    monkeypatch.setattr(probe, "UV", uv)
    monkeypatch.setattr(probe, "IMAGE_SHA", digest(image.read_bytes()))
    monkeypatch.setattr(probe, "UV_SHA", digest(uv.read_bytes()))
    manifests = {}
    for role in ("detector", "reconstructor", "sam"):
        path = root / f"data/models/{role}/manifest.json"
        json_file(path, {"artifacts": [{"path": "weights.bin"}]})
        (path.parent / "weights.bin").write_bytes(b"synthetic manifest asset: " + role.encode())
        manifests[role] = path
    monkeypatch.setattr(probe, "MANIFESTS", manifests)
    script = root / "tools/research_aging_pipeline_probe.py"
    monkeypatch.setattr(probe, "__file__", str(script))
    for relative in (
        "tools/research_aging_pipeline_probe.py",
        "tools/sam_worker.py",
        "backend/tests/test_research_aging_pipeline.py",
        "backend/tests/test_research_aging_pipeline_probe.py",
        "backend/src/agemorph3d/example.py",
        "data/third_party/SAM/models/example.py",
        "data/third_party/SAM/models/stylegan2/op/NATIVE_OPS.json",
        "docs/research-aging-pipeline-v1.json",
        ".gitignore",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic frozen input: " + relative.encode())
    json_file(
        root / "output/research/age-stage6-20261022/preserved-files.json",
        {"files": [probe.pin(root / ".gitignore")]},
    )
    return root


def arguments(root, name="probe"):
    return SimpleNamespace(
        output=root / "output/research" / name,
        target_condition=20,
        review_wait_seconds=30,
    )


def test_freeze_includes_source_uv_manifests_model_artifacts_and_protected_files(workspace):
    pins = probe.frozen_inputs()
    paths = [item["path"] for item in pins]
    assert len(paths) == len(set(paths)) and paths == sorted(paths)
    expected = {
        "data/source.jpg",
        "output/common-uv.npz",
        ".gitignore",
        "backend/src/agemorph3d/example.py",
        "data/third_party/SAM/models/example.py",
        "data/third_party/SAM/models/stylegan2/op/NATIVE_OPS.json",
        "tools/research_aging_pipeline_probe.py",
    }
    expected.update(f"data/models/{role}/weights.bin" for role in probe.MANIFESTS)
    expected.update(f"data/models/{role}/manifest.json" for role in probe.MANIFESTS)
    assert expected <= set(paths)
    for item in pins:
        data = (workspace / item["path"]).read_bytes()
        assert item["bytes"] == len(data) and item["sha256"] == digest(data)


@pytest.mark.parametrize(
    ("relative", "message"),
    [
        ("data/source.jpg", "Frozen development source changed"),
        ("output/common-uv.npz", "Frozen common UV changed"),
    ],
)
def test_freeze_rejects_reassigned_source_or_uv_content(workspace, relative, message):
    (workspace / relative).write_bytes(b"different content after expected fingerprint")
    with pytest.raises(ValueError, match=message):
        probe.frozen_inputs()


def test_freeze_preserves_current_protected_content_without_restoring_historical_snapshot(
    workspace,
):
    path = workspace / ".gitignore"
    current = b"current authorized content distinct from the historical snapshot"
    path.write_bytes(current)
    pins = {item["path"]: item for item in probe.frozen_inputs()}
    assert pins[".gitignore"] == {
        "path": ".gitignore",
        "bytes": len(current),
        "sha256": digest(current),
    }
    assert path.read_bytes() == current


def test_freeze_rejects_manifest_artifact_outside_workspace(workspace, tmp_path):
    external = tmp_path / "unrelated-secret.bin"
    external.write_bytes(b"unrelated file must not enter freeze")
    json_file(probe.MANIFESTS["detector"], {"artifacts": [{"path": str(external)}]})
    with pytest.raises(ValueError, match="inside the workspace"):
        probe.frozen_inputs()


def test_pin_rejects_sibling_with_same_workspace_prefix(workspace, tmp_path):
    sibling = tmp_path / (workspace.name + "-other")
    sibling.mkdir()
    external = sibling / "input.bin"
    external.write_bytes(b"outside")
    with pytest.raises(ValueError, match="inside the workspace"):
        probe.pin(external)


async def test_cli_freeze_failure_still_persists_failed_report_without_inference(
    workspace, monkeypatch
):
    def fail_freeze():
        raise ValueError("synthetic fingerprint mismatch before models")

    monkeypatch.setattr(probe, "frozen_inputs", fail_freeze)
    args = arguments(workspace)
    assert await probe.probe(args) == 1
    report = json.loads((args.output / "report.json").read_bytes())
    assert report["status"] == "failed" and report["error_code"] == "PROBE_FAILED"
    assert "fingerprint mismatch" in report["error"]
    assert report["inputs_checked"] == 0 and not report["inputs_unchanged"]
    assert report["cleanup_errors"] == []
    assert report["research_only"] and not report["service_ready"]
    assert not report["g3_complete"] and not report["quality_accepted"]
    assert report["source_age"] == {"value": None, "method": "unknown", "calibration_id": None}
    assert not (args.output / "freeze.json").exists()


async def test_cli_model_failure_and_close_environment_failures_all_reach_final_report(
    workspace, monkeypatch
):
    closed, calls = [], []

    def close_detector():
        closed.append("detector")
        raise RuntimeError("synthetic detector close failed")

    def construct(role, assets):
        if role == "detector":
            return SimpleNamespace(close=close_detector)
        raise ValueError("synthetic reconstructor construction failed")

    def environment():
        calls.append("environment")
        if len(calls) > 1:
            raise OSError("synthetic final environment inspection failed")
        return {"backend": "synthetic", "sam": "synthetic"}

    monkeypatch.setattr(probe, "environment", environment)
    monkeypatch.setattr(probe, "_construct_model", construct)
    monkeypatch.setattr(probe, "load_verified_manifest", lambda *args, **kwargs: object())
    args = arguments(workspace)
    assert await probe.probe(args) == 1
    report = json.loads((args.output / "report.json").read_bytes())
    freeze = json.loads((args.output / "freeze.json").read_bytes())
    assert closed == ["detector"] and len(calls) == 2
    assert "reconstructor construction failed" in report["error"]
    errors = {item["operation"]: item["error"] for item in report["cleanup_errors"]}
    assert "detector close failed" in errors["detector.close"]
    assert "final environment inspection failed" in errors["environment"]
    assert report["status"] == "failed" and report["inputs_unchanged"]
    assert report["inputs_checked"] == len(freeze["inputs"])
    assert freeze["source_age"] == report["source_age"]
    assert freeze["this_run_output_written_before_freeze"] is False
    assert freeze["same_source_condition_previously_inspected"] is True


async def test_cli_cleanup_still_closes_later_models_after_first_model_close_fails(
    workspace, monkeypatch
):
    closed = []

    def construct(role, assets):
        def close():
            closed.append(role)
            if role == "detector":
                raise RuntimeError("synthetic first model close failed")

        return SimpleNamespace(close=close)

    def fail_decode(*args, **kwargs):
        raise ValueError("synthetic input decode failed before inference")

    monkeypatch.setattr(probe, "environment", lambda: {"synthetic": "unchanged"})
    monkeypatch.setattr(probe, "_construct_model", construct)
    monkeypatch.setattr(probe, "load_verified_manifest", lambda *args, **kwargs: object())
    monkeypatch.setattr(probe, "decode_image", fail_decode)
    args = arguments(workspace)
    assert await probe.probe(args) == 1
    report = json.loads((args.output / "report.json").read_bytes())
    assert closed == ["detector", "reconstructor"]
    assert "input decode failed" in report["error"]
    assert [item["operation"] for item in report["cleanup_errors"]] == ["detector.close"]
    assert report["inputs_unchanged"] and report["environment_unchanged"]


async def test_cli_checks_all_frozen_inputs_after_a_changed_file_and_a_missing_file(
    workspace, monkeypatch
):
    inputs = [probe.pin(probe.IMAGE), probe.pin(probe.UV)]

    def fail_after_freeze(*args, **kwargs):
        probe.IMAGE.write_bytes(b"changed after freeze")
        probe.UV.unlink()
        raise ValueError("synthetic model setup failure")

    monkeypatch.setattr(probe, "frozen_inputs", lambda: inputs)
    monkeypatch.setattr(probe, "environment", lambda: {"synthetic": "unchanged"})
    monkeypatch.setattr(probe, "load_verified_manifest", fail_after_freeze)
    args = arguments(workspace)
    assert await probe.probe(args) == 1
    report = json.loads((args.output / "report.json").read_bytes())
    assert not report["inputs_unchanged"] and report["inputs_checked"] == 2
    assert [item["operation"] for item in report["cleanup_errors"]] == ["pin:output/common-uv.npz"]
    assert report["environment_unchanged"] and report["status"] == "failed"


async def test_cli_rejects_output_outside_research_before_creating_directory(workspace):
    args = arguments(workspace)
    args.output = workspace / "output/research-other/run"
    with pytest.raises(ValueError, match="under ignored output/research"):
        await probe.probe(args)
    assert not args.output.exists()


async def test_cli_never_overwrites_an_existing_run(workspace):
    args = arguments(workspace)
    args.output.mkdir(parents=True)
    sentinel = args.output / "report.json"
    sentinel.write_bytes(b"prior evidence")
    with pytest.raises(FileExistsError):
        await probe.probe(args)
    assert sentinel.read_bytes() == b"prior evidence"


def packed_glb(index_component, *, metadata="first", position_delta=0):
    position = struct.pack("<9f", *(float(i + position_delta) for i in range(9)))
    normal = struct.pack("<9f", *([0.0, 0.0, 1.0] * 3))
    uv = struct.pack("<6f", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0)
    indices = struct.pack("<3H" if index_component == 5123 else "<3I", 0, 1, 2)
    binary = b"prefix00" + position + normal + uv + indices
    binary += b"\0" * (-len(binary) % 4)
    document = {
        "asset": {"version": "2.0"},
        "extras": {"synthetic_provenance": metadata},
        "meshes": [
            {
                "primitives": [
                    {"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3}
                ]
            }
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 4, "byteLength": 40},
            {"buffer": 0, "byteOffset": 44, "byteLength": 36},
            {"buffer": 0, "byteOffset": 80, "byteLength": 24},
            {"buffer": 0, "byteOffset": 104, "byteLength": len(indices)},
        ],
        "accessors": [
            {"bufferView": 0, "byteOffset": 4, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC2"},
            {"bufferView": 3, "componentType": index_component, "count": 3, "type": "SCALAR"},
        ],
    }
    encoded = json.dumps(document, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    glb = (
        struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary))
        + struct.pack("<I4s", len(encoded), b"JSON")
        + encoded
        + struct.pack("<I4s", len(binary), b"BIN\0")
        + binary
    )
    return glb, {
        "POSITION": digest(position),
        "NORMAL": digest(normal),
        "TEXCOORD_0": digest(uv),
        "indices": digest(indices),
    }


@pytest.mark.parametrize("index_component", [5123, 5125])
def test_geometry_hashes_actual_accessor_offsets_and_component_widths(index_component):
    glb, expected = packed_glb(index_component)
    document, actual = probe.geometry(glb)
    assert actual == expected
    assert document["extras"]["synthetic_provenance"] == "first"


def test_geometry_comparison_ignores_provenance_but_detects_changed_positions():
    original, _ = packed_glb(5125)
    metadata, _ = packed_glb(5125, metadata="new target provenance")
    shifted, _ = packed_glb(5125, position_delta=1)
    assert original != metadata
    assert probe.geometry(original)[1] == probe.geometry(metadata)[1]
    before, after = probe.geometry(original)[1], probe.geometry(shifted)[1]
    assert before["POSITION"] != after["POSITION"]
    assert all(before[key] == after[key] for key in ("NORMAL", "TEXCOORD_0", "indices"))


@pytest.mark.parametrize("corruption", ["magic", "total_length", "chunk_kind"])
def test_geometry_rejects_invalid_container_identity(corruption):
    glb = bytearray(packed_glb(5125)[0])
    if corruption == "magic":
        glb[:4] = b"BAD!"
    elif corruption == "total_length":
        struct.pack_into("<I", glb, 8, len(glb) + 4)
    else:
        glb[16:20] = b"BAD!"
    with pytest.raises(ValueError):
        probe.geometry(bytes(glb))

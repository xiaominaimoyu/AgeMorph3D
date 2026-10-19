"""Lifecycle evidence uses synthetic adapters, never real-weight acceptance."""

import asyncio
import builtins
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from threading import Event, get_ident
from types import SimpleNamespace

import pytest

from agemorph3d import model_lifecycle
from agemorph3d.config import Settings
from agemorph3d.errors import ApiError
from agemorph3d.model_lifecycle import (
    LoadedModel,
    ModelLifecycle,
    ModelLoadError,
    detector_selftest,
    load_model,
    reconstructor_selftest,
)
from agemorph3d.runtime import Runtime


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    content = b"synthetic lifecycle fixture, not an ONNX model"
    (tmp_path / "fixture.onnx").write_bytes(content)
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "model_id": "synthetic-detector",
                "backend": "yolov5_face_onnx",
                "revision": "test-revision",
                "code_license": "synthetic-only",
                "code_license_url": "https://example.com/code-license",
                "weights_license": "synthetic-only",
                "weights_license_url": "https://example.com/weights-license",
                "license_status": "verified",
                "artifacts": [
                    {
                        "path": "fixture.onnx",
                        "source_url": "https://example.com/fixture.onnx",
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size_bytes": len(content),
                        "role": "detector",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_service_import_and_no_model_health_need_no_inference_dependencies() -> None:
    code = """
import importlib.abc
import sys
class BlockInference(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'numpy', 'cv2', 'onnxruntime'}:
            raise ImportError('inference dependency intentionally absent')
sys.meta_path.insert(0, BlockInference())
from fastapi.testclient import TestClient
from agemorph3d.app import create_app
from agemorph3d.config import Settings
with TestClient(create_app(Settings()), base_url='http://127.0.0.1') as client:
    response = client.get('/api/health')
    assert response.status_code == 200
    body = response.json()
    assert all(model['state'] == 'missing' for model in body['models'].values())
    assert not any(body['capabilities'].values())
assert not {'numpy', 'cv2', 'onnxruntime'} & set(sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=15, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("failure", ["unresolved", "hash", "invalid_json"])
def test_real_verifier_fails_closed_and_sanitizes_details(
    manifest_path: Path, failure: str
) -> None:
    if failure == "unresolved":
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["license_status"] = "unresolved"
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
    elif failure == "hash":
        artifact = manifest_path.parent / "fixture.onnx"
        artifact.write_bytes(b"x" * artifact.stat().st_size)
    else:
        manifest_path.write_text('{"private": "local-secret-path"}', encoding="utf-8")
    lifecycle = ModelLifecycle(Settings(detector_manifest=manifest_path))
    assert lifecycle.snapshot()["detector"].state == "missing"
    assert lifecycle.begin()
    assert lifecycle.snapshot()["detector"].state == "loading"
    lifecycle.initialize()
    status = lifecycle.snapshot()["detector"]
    assert status.state == "error"
    assert status.provider is None
    assert str(manifest_path) not in status.detail
    assert "local-secret-path" not in status.detail
    if failure == "unresolved":
        assert "许可" in status.detail
    lifecycle.close()


def test_missing_manifest_stays_missing(tmp_path: Path) -> None:
    lifecycle = ModelLifecycle(Settings(detector_manifest=tmp_path / "absent.json"))
    lifecycle.begin()
    lifecycle.initialize()
    assert lifecycle.snapshot()["detector"].state == "missing"
    lifecycle.close()


def test_import_failure_is_readiness_error_without_local_details(
    manifest_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_import = builtins.__import__

    def missing_dependency(name, *args, **kwargs):
        if name == "detector":
            raise ImportError("private/path/site-packages/secret")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_dependency)
    with pytest.raises(ModelLoadError, match="推理依赖") as caught:
        load_model("detector", manifest_path)
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("failure", [None, "construct", "selftest", "provider"])
def test_loader_requires_construction_and_selftest_and_disposes_failures(
    manifest_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    np = pytest.importorskip("numpy")
    calls = []

    class SyntheticDetector:
        provider = "WrongProvider" if failure == "provider" else "CPUExecutionProvider"
        license_verified = True

        def __init__(self, assets):
            calls.append("construct")
            assert assets.license_verified
            if failure == "construct":
                raise RuntimeError("private/model/path")

        def detect(self, rgb):
            calls.append("detect")
            assert rgb.dtype == np.uint8
            assert rgb.shape == (640, 640, 3)
            assert not rgb.any()
            if failure == "selftest":
                raise RuntimeError("private/photo/path")
            return []

        def close(self):
            calls.append("close")

    monkeypatch.setitem(
        sys.modules,
        "agemorph3d.detector",
        SimpleNamespace(Yolo5FaceOnnx=SyntheticDetector),
    )
    if failure:
        with pytest.raises(ModelLoadError) as caught:
            load_model("detector", manifest_path)
        assert "private" not in str(caught.value)
        assert calls == (
            ["construct"]
            if failure == "construct"
            else ["construct", "close"]
            if failure == "provider"
            else ["construct", "detect", "close"]
        )
    else:
        loaded = load_model("detector", manifest_path)
        assert loaded.backend == "yolov5_face_onnx"
        assert loaded.provider == "CPUExecutionProvider"
        assert calls == ["construct", "detect"]
        loaded.close()
        loaded.close()
        assert calls == ["construct", "detect", "close"]
        assert loaded.instance is None


async def wait_for_state(runtime: Runtime, name: str, state: str) -> None:
    async def wait() -> None:
        while runtime.health().models[name].state != state:  # noqa: ASYNC110
            await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout=2)


async def test_start_is_nonblocking_once_and_uses_same_bounded_worker(
    manifest_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = Event(), Event()
    loads, closed = [], []

    def loader(name, path):
        loads.append((name, path, get_ident()))
        entered.set()
        assert release.wait(5)
        return LoadedModel(
            "yolov5_face_onnx",
            "CPUExecutionProvider",
            SimpleNamespace(close=lambda: closed.append(get_ident())),
        )

    monkeypatch.setattr(model_lifecycle, "load_model", loader)
    runtime = Runtime(Settings(detector_manifest=manifest_path))
    try:
        await asyncio.wait_for(runtime.start(), timeout=0.5)
        assert await asyncio.to_thread(entered.wait, 1)
        assert runtime.health().models["detector"].state == "loading"
        await runtime.start()
        with pytest.raises(ApiError) as caught:
            await runtime.run(lambda: "cannot queue", timeout=1)
        assert caught.value.code == "BUSY"
        release.set()
        await wait_for_state(runtime, "detector", "ready")
        # A state update can precede the worker future's completion callback.
        assert runtime._initialization is not None
        await asyncio.wait_for(asyncio.shield(runtime._initialization), timeout=1)
        worker_id = await runtime.run(get_ident, timeout=1)
        assert len(loads) == 1 and loads[0][2] == worker_id
        assert runtime.health().models["detector"].backend == "yolov5_face_onnx"
        assert not any(runtime.health().capabilities.model_dump().values())
        snapshot = runtime.health()
        snapshot.models["detector"].state = "error"
        assert runtime.health().models["detector"].state == "ready"
    finally:
        release.set()
        await runtime.close()
    assert runtime.health().models["detector"].state == "missing"
    assert closed == [loads[0][2]]


async def test_close_during_initialization_disposes_late_model_and_cannot_restart(
    manifest_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release, disposed = Event(), Event(), Event()
    calls = []

    def loader(name, path):
        calls.append(name)
        entered.set()
        assert release.wait(5)
        return LoadedModel(
            "yolov5_face_onnx", "CPUExecutionProvider", SimpleNamespace(close=disposed.set)
        )

    monkeypatch.setattr(model_lifecycle, "load_model", loader)
    runtime = Runtime(Settings(detector_manifest=manifest_path))
    await runtime.start()
    shutdown = None
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        shutdown = asyncio.create_task(runtime.close())
        await asyncio.sleep(0)
        assert not shutdown.done()
        assert runtime.health().models["detector"].state == "missing"
        shutdown.cancel()
        with pytest.raises(asyncio.CancelledError):
            await shutdown
        with pytest.raises(ApiError) as caught:
            await runtime.run(lambda: None, timeout=1)
        assert caught.value.code == "MODEL_NOT_READY"
        await runtime.start()
        release.set()
        await asyncio.wait_for(runtime.close(), timeout=2)
        assert disposed.is_set()
        assert calls == ["detector"]
        assert all(status.state != "ready" for status in runtime.health().models.values())
    finally:
        release.set()
        if shutdown is not None:
            await asyncio.gather(shutdown, return_exceptions=True)
        await runtime.close()


async def test_unexpected_loader_error_is_sanitized_and_does_not_block_other_models(
    manifest_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def loader(name, path):
        if name == "detector":
            raise RuntimeError(f"secret data at {path}")
        return LoadedModel("3ddfa_v2_onnx", "CPUExecutionProvider", SimpleNamespace())

    monkeypatch.setattr(model_lifecycle, "load_model", loader)
    runtime = Runtime(
        Settings(detector_manifest=manifest_path, reconstructor_manifest=manifest_path)
    )
    try:
        await runtime.start()
        await wait_for_state(runtime, "reconstructor", "ready")
        assert runtime.health().models["detector"].state == "error"
        assert "secret" not in runtime.health().models["detector"].detail
        assert str(manifest_path) not in runtime.health().models["detector"].detail
        assert not any(runtime.health().capabilities.model_dump().values())
    finally:
        await runtime.close()


@pytest.mark.parametrize("field", ["bbox", "landmarks", "confidence"])
def test_detector_selftest_rejects_nonfinite_outputs(field: str) -> None:
    np = pytest.importorskip("numpy")
    values = {"bbox": [1, 2, 3, 4], "landmarks": [[1, 2]] * 5, "confidence": 0.9}
    values[field] = np.full(np.asarray(values[field]).shape, np.nan)
    with pytest.raises(ValueError):
        detector_selftest(SimpleNamespace(detect=lambda _rgb: [SimpleNamespace(**values)]))


@pytest.mark.parametrize("failure", [None, "shape", "triangle", "projection", "canonical_pose"])
def test_reconstructor_selftest_runs_image_projection_and_validates_mesh(
    failure: str | None,
) -> None:
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    pytest.importorskip("onnxruntime")
    from agemorph3d.tddfa import TddfaResult

    projection = np.eye(3, 4, dtype=np.float32)
    if failure == "projection":
        projection[:] = np.nan
    elif failure == "canonical_pose":
        projection[2, 2] = -1
    result = TddfaResult(
        shape=np.zeros(40 if failure != "shape" else 39),
        expr=np.zeros(10),
        vertices=np.array([[1, 20, 3], [61, 80, 8], [5, 10, 5]], dtype=np.float32),
        triangles=np.array([[0, 1, 2 if failure != "triangle" else 3]]),
        projection=projection,
        roi=(0, 0, 120, 120),
        topology_sha256="ab" * 32,
    )
    calls = []

    def reconstruct(rgb, bbox):
        calls.append(bbox)
        assert rgb.shape == (120, 120, 3) and rgb.dtype == np.uint8
        return result

    model = SimpleNamespace(
        reconstruct=reconstruct,
        topology_sha256="ab" * 32,
        keypoint_coordinates=(np.arange(204) % 9).reshape(68, 3),
    )
    if failure:
        with pytest.raises(ValueError):
            reconstructor_selftest(model)
    else:
        reconstructor_selftest(model)
    assert calls == [(20, 20, 80, 80)]

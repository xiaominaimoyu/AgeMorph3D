"""Synthetic service integration evidence; these tests do not accept real weights or G1."""

import asyncio
import io
import json
import struct
import time
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from agemorph3d import model_lifecycle
from agemorph3d.app import MeshResponse, create_app
from agemorph3d.asset_cache import AssetCache
from agemorph3d.config import Settings
from agemorph3d.errors import ApiError
from agemorph3d.model_lifecycle import LoadedModel

np = pytest.importorskip("numpy")


class SyntheticDetector:
    def __init__(self) -> None:
        self.face_count = 1
        self.failure: Exception | None = None
        self.started: Event | None = None
        self.release: Event | None = None

    def detect(self, rgb):
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            assert self.release.wait(5)
        if self.failure is not None:
            raise self.failure
        return [SimpleNamespace(bbox=(1, 1, 20, 20)) for _ in range(self.face_count)]


class SyntheticReconstructor:
    def __init__(self) -> None:
        self.failure: Exception | None = None

    def reconstruct(self, rgb, bbox):
        if self.failure is not None:
            raise self.failure
        identity = float(rgb[0, 0, 0]) / 255
        return SimpleNamespace(
            shape=np.full(40, identity, dtype=np.float32),
            expr=np.linspace(0, 0.1, 10, dtype=np.float32),
            vertices=np.array(
                [[-1 - identity, -1, 0], [0, 1, 1], [1 + identity, -1, 0]], dtype=np.float32
            ),
            triangles=np.array([[0, 1, 2]], dtype=np.int64),
            projection=np.column_stack((np.eye(3), np.array([2, 3, 4]))),
            roi=(0, 0, 24, 24),
            topology_sha256="a" * 64,
            coordinate_system="bfm_model_raw",
        )


def image_upload(red: int = 40) -> dict:
    data = io.BytesIO()
    Image.new("RGB", (24, 24), (red, 12, 30)).save(data, format="PNG")
    return {"image": ("synthetic-photo.png", data.getvalue(), "image/png")}


def glb_document(data: bytes) -> dict:
    magic, version, length = struct.unpack_from("<4sII", data)
    assert (magic, version, length) == (b"glTF", 2, len(data))
    json_length, chunk_type = struct.unpack_from("<I4s", data, 12)
    assert chunk_type == b"JSON"
    return json.loads(data[20 : 20 + json_length])


@pytest.fixture
def synthetic_service(monkeypatch, tmp_path: Path):
    detector, reconstructor = SyntheticDetector(), SyntheticReconstructor()
    manifest = tmp_path / "synthetic-manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    def load_model(name, _path):
        return LoadedModel(
            "yolov5_face_onnx" if name == "detector" else "3ddfa_v2_onnx",
            "CPUExecutionProvider",
            detector if name == "detector" else reconstructor,
        )

    monkeypatch.setattr(model_lifecycle, "load_model", load_model)

    @asynccontextmanager
    async def service(**overrides):
        app = create_app(
            Settings(detector_manifest=manifest, reconstructor_manifest=manifest, **overrides)
        )
        async with app.router.lifespan_context(app):
            runtime = app.state.runtime
            await asyncio.wait_for(asyncio.shield(runtime._initialization), timeout=2)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
            ) as client:
                yield SimpleNamespace(
                    app=app,
                    client=client,
                    runtime=runtime,
                    detector=detector,
                    reconstructor=reconstructor,
                )

    return service


@pytest.fixture
def publications(monkeypatch):
    identifiers = []
    publish = AssetCache.publish

    def recording_publish(cache, data):
        mesh_id = publish(cache, data)
        identifiers.append(mesh_id)
        return mesh_id

    monkeypatch.setattr(AssetCache, "publish", recording_publish)
    return identifiers


async def eventually_idle(runtime) -> None:
    async def wait() -> None:
        while True:
            try:
                await runtime.run(lambda: None, timeout=1)
                return
            except ApiError as error:
                if error.code != "BUSY":
                    raise
                await asyncio.sleep(0)

    await asyncio.wait_for(wait(), timeout=2)


async def test_ready_models_enable_static_and_realtime(synthetic_service) -> None:
    async with synthetic_service() as service:
        body = (await service.client.get("/api/health")).json()
        assert body["api_version"] == "1.2"
        assert body["models"]["detector"]["state"] == "ready"
        assert body["models"]["reconstructor"]["state"] == "ready"
        assert body["capabilities"] == {
            "reconstruction": True,
            "age_morph": False,
            "age_texture": False,
            "realtime": True,
        }
        response = await service.client.post("/api/aging", json={"mesh_id": "abc", "age": 40})
        assert response.status_code == 503


async def test_configured_uv_embeds_observed_base_photo_in_cached_static_asset(synthetic_service):
    async with synthetic_service() as service:
        # Explicit synthetic UV, not an age model or real-weight acceptance.
        service.reconstructor.uv = np.array([[0, 0], [0.5, 1], [1, 0]], dtype=np.float32)
        response = await service.client.post("/api/reconstruct", files=image_upload())
        assert response.status_code == 200
        result = response.json()
        assert result["asset_mode"] == "static"
        assert result["source_age"]["value"] is None
        assert result["capabilities"] == {"age_morph": False, "age_texture": False}
        assert result["texture_url"] is None
        mesh = await service.client.get(f"/api/assets/{result['mesh_id']}/mesh.glb")
        assert mesh.status_code == 200 and mesh.headers["content-type"] == "model/gltf-binary"
        document = glb_document(mesh.content)
        assert document["images"][0]["mimeType"] == "image/png"
        assert "TEXCOORD_0" in document["meshes"][0]["primitives"][0]["attributes"]
        assert document["extras"]["base_texture"]["age_generated"] is False
        assert document["materials"][0]["alphaMode"] == "MASK"
        assert not any("uri" in item for item in document["images"] + document["buffers"])


@pytest.mark.parametrize("source_age", [None, "42.5"])
async def test_photo_produces_static_contract_and_standalone_glb(
    synthetic_service, source_age: str | None
) -> None:
    async with synthetic_service() as service:
        response = await service.client.post(
            "/api/reconstruct",
            files=image_upload(),
            data={} if source_age is None else {"source_age": source_age},
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["asset_mode"] == "static"
        assert body["capabilities"] == {"age_morph": False, "age_texture": False}
        assert body["texture_url"] is None
        assert len(body["shape"]) == 40 and len(body["expr"]) == 10
        assert body["topology_id"] == "tddfa-bfm-canon-v1-" + "a" * 64
        expected_age = {
            "value": None if source_age is None else 42.5,
            "method": "unknown" if source_age is None else "user",
            "calibration_id": None,
        }
        assert body["source_age"] == expected_age
        assert body["pose"] == {"R": np.eye(3).reshape(-1).tolist(), "t": [0, 0, 0]}
        mesh = await service.client.get(
            f"/api/assets/{body['mesh_id']}/mesh.glb",
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        assert mesh.status_code == 200
        assert mesh.headers["content-type"] == "model/gltf-binary"
        assert int(mesh.headers["content-length"]) == len(mesh.content)
        assert mesh.headers["cache-control"] == "no-store"
        assert mesh.headers["x-content-type-options"] == "nosniff"
        assert mesh.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
        document = glb_document(mesh.content)
        assert document["extras"]["asset_mode"] == "static"
        assert document["extras"]["source_age"] == expected_age
        assert document["extras"]["topology_id"] == body["topology_id"]
        assert not any(key in document for key in ("images", "textures", "animations"))
        primitive = document["meshes"][0]["primitives"][0]
        assert "targets" not in primitive
        assert document["accessors"][0]["count"] == 3
        assert document["accessors"][2]["count"] == 3


async def test_each_photo_retains_its_own_shape_and_mesh(synthetic_service) -> None:
    async with synthetic_service() as service:
        first = (await service.client.post("/api/reconstruct", files=image_upload(20))).json()
        second = (await service.client.post("/api/reconstruct", files=image_upload(180))).json()
        assert first["mesh_id"] != second["mesh_id"]
        assert first["shape"] != second["shape"]
        first_mesh = await service.client.get(f"/api/assets/{first['mesh_id']}/mesh.glb")
        second_mesh = await service.client.get(f"/api/assets/{second['mesh_id']}/mesh.glb")
        assert first_mesh.content != second_mesh.content
        assert first["topology_id"] == second["topology_id"]


@pytest.mark.parametrize("face_count,code", [(0, "NO_FACE"), (2, "MULTI_FACE")])
async def test_face_count_errors_recover_for_next_photo(
    synthetic_service, publications, face_count: int, code: str
) -> None:
    async with synthetic_service() as service:
        service.detector.face_count = face_count
        response = await service.client.post("/api/reconstruct", files=image_upload())
        assert response.status_code == 422
        assert response.json()["code"] == code
        assert publications == []
        service.detector.face_count = 1
        response = await service.client.post("/api/reconstruct", files=image_upload())
        assert response.status_code == 200
        assert publications == [response.json()["mesh_id"]]


@pytest.mark.parametrize("adapter", ["detector", "reconstructor"])
async def test_private_inference_failure_is_sanitized_and_recoverable(
    synthetic_service, publications, adapter: str
) -> None:
    async with synthetic_service() as service:
        model = getattr(service, adapter)
        model.failure = RuntimeError("private-photo-name D:/private/model-secret.onnx")
        response = await service.client.post("/api/reconstruct", files=image_upload())
        assert response.status_code == 500
        assert response.json()["code"] == "RECONSTRUCTION_FAILED"
        assert "private" not in response.text and "onnx" not in response.text
        assert publications == []
        model.failure = None
        assert (
            await service.client.post("/api/reconstruct", files=image_upload())
        ).status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/api/assets/" + "0" * 32 + "/mesh.glb",
        "/api/assets/..%2fprivate/mesh.glb",
        "/api/assets/%252e%252e%252fprivate/mesh.glb",
        "/api/assets/..%5cprivate/mesh.glb",
        "/api/assets/" + "A" * 32 + "/mesh.glb",
    ],
)
async def test_unknown_and_path_like_assets_never_read_files(synthetic_service, path: str) -> None:
    async with synthetic_service() as service:
        response = await service.client.get(path)
        assert response.status_code == 404
        assert response.headers["cache-control"] == "no-store"
        assert "private" not in response.text


async def test_asset_ttl_returns_safe_missing_response(synthetic_service) -> None:
    async with synthetic_service(asset_ttl_seconds=10) as service:
        now = [100.0]
        service.runtime._assets._clock = lambda: now[0]
        result = (await service.client.post("/api/reconstruct", files=image_upload())).json()
        path = f"/api/assets/{result['mesh_id']}/mesh.glb"
        assert (await service.client.get(path)).status_code == 200
        now[0] = 110
        response = await service.client.get(path)
        assert response.status_code == 404
        assert response.json()["code"] == "ASSET_NOT_FOUND"


async def test_asset_size_budget_fails_publication_without_disabling_models(
    synthetic_service, publications
) -> None:
    async with synthetic_service(asset_cache_bytes=1) as service:
        response = await service.client.post("/api/reconstruct", files=image_upload())
        assert response.status_code == 429
        assert response.json()["code"] == "BUSY"
        assert response.headers["retry-after"] == "1"
        assert publications == []
        assert (await service.client.get("/api/health")).json()["capabilities"]["reconstruction"]


async def test_active_asset_read_blocks_eviction_and_publication_recovers(
    synthetic_service,
) -> None:
    async with synthetic_service(asset_cache_entries=1) as service:
        first = (await service.client.post("/api/reconstruct", files=image_upload())).json()
        lease = service.runtime.acquire_mesh(first["mesh_id"])
        try:
            response = await service.client.post("/api/reconstruct", files=image_upload(180))
            assert response.status_code == 429
            assert glb_document(lease.data)["extras"]["topology_id"] == first["topology_id"]
        finally:
            lease.close()
        replacement = await service.client.post("/api/reconstruct", files=image_upload(180))
        assert replacement.status_code == 200
        assert (
            await service.client.get(f"/api/assets/{first['mesh_id']}/mesh.glb")
        ).status_code == 404


@pytest.mark.parametrize("abandon", ["timeout", "cancel"])
async def test_abandoned_request_keeps_worker_busy_and_never_publishes_late_result(
    synthetic_service, publications, abandon: str
) -> None:
    async with synthetic_service(
        http_timeout_seconds=0.15 if abandon == "timeout" else 3
    ) as service:
        started, release = Event(), Event()
        service.detector.started, service.detector.release = started, release
        request = asyncio.create_task(service.client.post("/api/reconstruct", files=image_upload()))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            if abandon == "timeout":
                response = await request
                assert response.status_code == 504
                assert response.json()["code"] == "TIMEOUT"
            else:
                request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await request
            assert publications == []
            busy = await service.client.post("/api/reconstruct", files=image_upload())
            assert busy.status_code == 429
            release.set()
            await eventually_idle(service.runtime)
            assert publications == []
            service.detector.release = None
            recovery = await service.client.post("/api/reconstruct", files=image_upload())
            assert recovery.status_code == 200
            assert publications == [recovery.json()["mesh_id"]]
        finally:
            release.set()
            await asyncio.gather(request, return_exceptions=True)


async def test_completed_worker_cannot_publish_after_event_loop_resumes_past_deadline(
    synthetic_service, publications, monkeypatch
) -> None:
    async with synthetic_service(http_timeout_seconds=0.25) as service:
        prepare = service.runtime.prepare_static
        completed = []

        async def prepare_then_stall(*args):
            prepared = await prepare(*args)
            completed.append(True)
            # A busy event loop can resume the endpoint after the worker's own
            # wait succeeded. The absolute HTTP deadline still forbids publication.
            time.sleep(0.3)  # noqa: ASYNC251 -- deliberately simulate an event-loop stall
            return prepared

        monkeypatch.setattr(service.runtime, "prepare_static", prepare_then_stall)
        response = await service.client.post("/api/reconstruct", files=image_upload())
        assert completed == [True], "This case must reach completed inference before stalling."
        assert response.status_code == 504
        assert response.json()["code"] == "TIMEOUT"
        assert publications == []
        assert await service.runtime.run(lambda: "worker is free", timeout=1) == "worker is free"


def request_scope(path: str, content_type: str = "", length: int = 0) -> dict:
    headers = [(b"host", b"127.0.0.1")]
    if content_type:
        headers.extend(
            [(b"content-type", content_type.encode()), (b"content-length", str(length).encode())]
        )
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST" if content_type else "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 80),
    }


async def test_disconnect_before_worker_completion_does_not_publish(
    synthetic_service, publications
):
    async with synthetic_service() as service:
        started, release = Event(), Event()
        service.detector.started, service.detector.release = started, release
        upload = httpx.Request("POST", "http://127.0.0.1/api/reconstruct", files=image_upload())
        body = upload.read()
        scope = request_scope("/api/reconstruct", upload.headers["content-type"], len(body))
        disconnected = asyncio.Event()
        delivered = False
        sent = []

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        request = asyncio.create_task(service.app(scope, receive, send))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            disconnected.set()
            await asyncio.wait_for(request, timeout=1)
            assert publications == []
            assert (
                next(message for message in sent if message["type"] == "http.response.start")[
                    "status"
                ]
                == 499
            )
            with pytest.raises(ApiError) as busy:
                await service.runtime.run(lambda: None, timeout=1)
            assert busy.value.code == "BUSY"
            release.set()
            await eventually_idle(service.runtime)
            assert publications == []
        finally:
            release.set()
            disconnected.set()
            await asyncio.gather(request, return_exceptions=True)


async def test_shutdown_during_worker_prevents_late_publication(synthetic_service, publications):
    async with synthetic_service() as service:
        started, release = Event(), Event()
        service.detector.started, service.detector.release = started, release
        request = asyncio.create_task(service.client.post("/api/reconstruct", files=image_upload()))
        shutdown = None
        try:
            assert await asyncio.to_thread(started.wait, 1)
            shutdown = asyncio.create_task(service.runtime.close())
            await asyncio.sleep(0)
            assert not shutdown.done()
            assert not service.runtime.health().capabilities.reconstruction
            release.set()
            response = await request
            assert response.status_code == 503
            await asyncio.wait_for(shutdown, timeout=2)
            assert publications == []
        finally:
            release.set()
            await asyncio.gather(request, return_exceptions=True)
            if shutdown is not None:
                await shutdown


@pytest.mark.parametrize("failure", ["error", "cancel"])
async def test_asset_response_releases_pin_on_asgi_send_failure(failure: str) -> None:
    cache = AssetCache(max_entries=1)
    mesh_id = cache.publish(b"synthetic GLB")
    response = MeshResponse(cache.acquire(mesh_id))
    sending = asyncio.Event()

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.body":
            sending.set()
            if failure == "error":
                raise OSError("synthetic disconnected response")
            await asyncio.Event().wait()

    task = asyncio.create_task(response(request_scope("/api/assets/id/mesh.glb"), receive, send))
    assert await asyncio.wait_for(sending.wait(), timeout=1)
    if failure == "error":
        with pytest.raises(OSError):
            await task
    else:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    cache.publish(b"replacement proves no pinned leak")
    cache.close()


def test_asset_cache_configuration_environment(monkeypatch) -> None:
    monkeypatch.setenv("AGEMORPH_ASSET_MAX_BYTES", "4096")
    monkeypatch.setenv("AGEMORPH_ASSET_MAX_ENTRIES", "3")
    monkeypatch.setenv("AGEMORPH_ASSET_TTL_SECONDS", "2.5")
    settings = Settings.from_env()
    assert settings.asset_cache_bytes == 4096
    assert settings.asset_cache_entries == 3
    assert settings.asset_ttl_seconds == 2.5


@pytest.mark.parametrize(
    "variable,value",
    [
        ("AGEMORPH_ASSET_MAX_BYTES", "0"),
        ("AGEMORPH_ASSET_MAX_ENTRIES", "1.5"),
        ("AGEMORPH_ASSET_TTL_SECONDS", "nan"),
        ("AGEMORPH_ASSET_TTL_SECONDS", "inf"),
        ("AGEMORPH_ASSET_TTL_SECONDS", "-1"),
    ],
)
def test_invalid_asset_cache_environment_fails_early(
    monkeypatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError):
        Settings.from_env()

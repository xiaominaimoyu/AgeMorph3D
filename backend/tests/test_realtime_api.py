"""Synthetic transport/race evidence; real device and licensed-model gates are separate."""

import asyncio
import io
import json
import time
from contextlib import asynccontextmanager
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from agemorph3d import model_lifecycle
from agemorph3d.app import create_app
from agemorph3d.asset_cache import AssetCache
from agemorph3d.config import Settings
from agemorph3d.errors import ApiError
from agemorph3d.frame_socket import face_message
from agemorph3d.model_lifecycle import LoadedModel

np = pytest.importorskip("numpy")
ORIGIN = "http://127.0.0.1:5173"


def jpeg() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 40), (24, 36, 82)).save(output, "JPEG")
    return output.getvalue()


class Detector:
    def __init__(self):
        self.faces = 1
        self.calls = 0
        self.started = Event()
        self.release = Event()
        self.release.set()
        self.failure = None

    def detect(self, _rgb):
        self.calls += 1
        self.started.set()
        assert self.release.wait(5)
        if self.failure is not None:
            raise self.failure
        return [
            SimpleNamespace(
                bbox=(7, 5, 23, 25),
                landmarks=((12, 12), (26, 11), (20, 19), (14, 25), (25, 26)),
                confidence=0.875,
            )
            for _ in range(self.faces)
        ]


class Reconstructor:
    def reconstruct(self, _rgb, _bbox):
        return SimpleNamespace(
            coordinate_system="bfm_model_raw",
            projection=np.column_stack((np.eye(3) * 0.003, [2, 3, 4])),
        )


@pytest.fixture
def models(monkeypatch, tmp_path):
    detector = Detector()
    manifest = tmp_path / "synthetic.json"
    manifest.write_text("{}")
    monkeypatch.setattr(
        model_lifecycle,
        "load_model",
        lambda name, _path: LoadedModel(
            "synthetic", "CPUExecutionProvider", detector if name == "detector" else Reconstructor()
        ),
    )
    settings = Settings(detector_manifest=manifest, reconstructor_manifest=manifest)
    return detector, settings


@asynccontextmanager
async def ws_app(settings, on_send=None):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        await asyncio.shield(app.state.runtime._initialization)
        inputs = asyncio.Queue()
        outputs = asyncio.Queue()

        async def send(message):
            if on_send is not None:
                await on_send(message)
            await outputs.put(message)

        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "scheme": "ws",
            "path": "/ws/frame",
            "raw_path": b"/ws/frame",
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", b"127.0.0.1"), (b"origin", ORIGIN.encode())],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
            "subprotocols": [],
            "state": {},
        }
        await inputs.put({"type": "websocket.connect"})
        task = asyncio.create_task(app(scope, inputs.get, send))

        async def reply():
            message = await asyncio.wait_for(outputs.get(), timeout=2)
            if message["type"] == "websocket.send":
                assert len(message["text"].encode()) <= 1024
                return json.loads(message["text"])
            return message

        assert (await reply())["type"] == "websocket.accept"
        assert await reply() == {"type": "status", "device": "cpu"}
        try:
            yield SimpleNamespace(
                app=app,
                runtime=app.state.runtime,
                inputs=inputs,
                outputs=outputs,
                task=task,
                reply=reply,
            )
        finally:
            await inputs.put({"type": "websocket.disconnect", "code": 1000})
            await asyncio.wait_for(task, timeout=2)


async def send_frame(ws):
    await ws.inputs.put({"type": "websocket.receive", "bytes": jpeg()})


async def test_success_recovery_and_sequence_share_one_socket_without_assets(models, monkeypatch):
    detector, settings = models

    def forbidden(*_args, **_kwargs):
        pytest.fail("Realtime frames must not publish assets.")

    monkeypatch.setattr(AssetCache, "publish", forbidden)
    async with ws_app(settings) as ws:
        health = ws.runtime.health()
        assert health.capabilities.realtime and health.capabilities.reconstruction
        assert not health.capabilities.age_morph and not health.capabilities.age_texture
        for seq, count in enumerate((1, 0, 2, 1), 1):
            detector.faces = count
            await send_frame(ws)
            body = await ws.reply()
            assert body["seq"] == seq
            if count == 1:
                assert body["type"] == "face_state"
                assert body["bbox"] == [7, 5, 23, 25]
                assert len(body["landmarks"]) == 5
                assert body["pose"]["t"] == [0, 0, 0]
                assert body["ts"] > 0
                assert not {"shape", "expr", "mesh_id"} & body.keys()
            else:
                assert body["code"] == ("NO_FACE" if count == 0 else "MULTI_FACE")
            assert not ws.task.done()


async def test_global_busy_recovers_without_enqueuing_another_frame(models):
    detector, settings = models
    started, release = Event(), Event()

    def blocked():
        started.set()
        assert release.wait(5)

    async with ws_app(settings) as ws:
        other = asyncio.create_task(ws.runtime.run(blocked, timeout=2))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            await send_frame(ws)
            assert (await ws.reply())["code"] == "BUSY"
            assert detector.calls == 0
            release.set()
            await other
            await send_frame(ws)
            assert (await ws.reply())["type"] == "face_state"
        finally:
            release.set()
            await other


async def test_disconnect_discards_result_but_holds_native_worker_slot(models):
    detector, settings = models
    detector.release.clear()
    try:
        async with ws_app(settings) as ws:
            await send_frame(ws)
            assert await asyncio.to_thread(detector.started.wait, 1)
            await ws.inputs.put({"type": "websocket.disconnect", "code": 1000})
            await asyncio.wait_for(ws.task, timeout=1)
            assert ws.outputs.empty()
            with pytest.raises(ApiError) as caught:
                await ws.runtime.run(lambda: None, timeout=1)
            assert caught.value.code == "BUSY"
            detector.release.set()
    finally:
        detector.release.set()


async def test_pipeline_violation_terminal_errors_are_bounded_and_do_not_queue(models):
    detector, settings = models
    detector.release.clear()
    try:
        async with ws_app(settings) as ws:
            await send_frame(ws)
            assert await asyncio.to_thread(detector.started.wait, 1)
            await send_frame(ws)
            replies = [await ws.reply(), await ws.reply()]
            assert [body["seq"] for body in replies] == [1, 2]
            assert all(body["code"] == "BUSY" for body in replies)
            assert await ws.reply() == {"type": "websocket.close", "code": 1013, "reason": ""}
            assert detector.calls == 1
            detector.release.set()
            await ws.task
            assert ws.outputs.empty()
    finally:
        detector.release.set()


async def test_timeout_never_releases_native_slot_early(models):
    detector, settings = models
    from dataclasses import replace

    settings = replace(settings, frame_timeout_seconds=0.03)
    detector.release.clear()
    try:
        async with ws_app(settings) as ws:
            await send_frame(ws)
            assert (await ws.reply())["code"] == "TIMEOUT"
            assert (await ws.reply())["code"] == 1013
            with pytest.raises(ApiError) as caught:
                await ws.runtime.run(lambda: None, timeout=1)
            assert caught.value.code == "BUSY"
            detector.release.set()
    finally:
        detector.release.set()


async def test_event_loop_stall_cannot_send_late_success(models, monkeypatch):
    _detector, settings = models
    from dataclasses import replace

    settings = replace(settings, frame_timeout_seconds=0.02)
    original = None

    async with ws_app(settings) as ws:
        original = ws.runtime.process_frame

        async def stall(data, budget):
            result = await original(data, budget)
            time.sleep(0.04)  # noqa: ASYNC251 - deliberately stall past the absolute deadline.
            return result

        monkeypatch.setattr(ws.runtime, "process_frame", stall)
        await send_frame(ws)
        assert (await ws.reply())["code"] == "TIMEOUT"
        assert (await ws.reply())["code"] == 1013


async def test_model_failure_is_sanitized_and_fatal(models):
    detector, settings = models
    detector.failure = RuntimeError("private-photo-path-and-parameters")
    async with ws_app(settings) as ws:
        await send_frame(ws)
        body = await ws.reply()
        assert body["code"] == "POSE_FAILED"
        assert "private" not in json.dumps(body)
        assert (await ws.reply())["code"] == 1011


async def test_slow_asgi_send_cannot_deliver_success_after_frame_deadline(models):
    from dataclasses import replace

    _detector, settings = models
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def slow_send(message):
        if message["type"] == "websocket.send" and '"face_state"' in message["text"]:
            started.set()
            try:
                await asyncio.sleep(0.3)
            except asyncio.CancelledError:
                cancelled.set()
                raise

    async with ws_app(replace(settings, frame_timeout_seconds=0.05), slow_send) as ws:
        await send_frame(ws)
        await asyncio.wait_for(started.wait(), timeout=1)
        await asyncio.wait_for(ws.task, timeout=0.2)
        assert cancelled.is_set()
        assert ws.outputs.empty()  # Unknown send status must never trigger a duplicate reply.
        assert await ws.runtime.run(lambda: "available", timeout=1) == "available"


async def test_runtime_shutdown_during_frame_drops_late_success(models):
    detector, settings = models
    detector.release.clear()
    shutdown = None
    try:
        async with ws_app(settings) as ws:
            await send_frame(ws)
            assert await asyncio.to_thread(detector.started.wait, 1)
            shutdown = asyncio.create_task(ws.runtime.close())
            await asyncio.sleep(0)
            assert not ws.runtime.health().capabilities.realtime
            detector.release.set()
            assert (await ws.reply())["code"] == "MODEL_NOT_READY"
            assert (await ws.reply())["code"] == 1013
            await shutdown
    finally:
        detector.release.set()
        if shutdown is not None:
            await shutdown


def test_real_testclient_success_stays_under_one_kib(models):
    _detector, settings = models
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.portal.call(lambda: asyncio.shield(app.state.runtime._initialization))
        with client.websocket_connect(
            "ws://127.0.0.1/ws/frame", headers={"origin": ORIGIN}
        ) as socket:
            socket.receive_json()
            socket.send_bytes(jpeg())
            text = socket.receive_text()
            assert len(text.encode()) <= 1024
            assert json.loads(text)["type"] == "face_state"


def test_numeric_compaction_preserves_small_box_and_rotation():
    result = {
        "bbox": [0.00000000017, 0, 0.00000000001, 640],
        "landmarks": [[-16384.0, 16384.0]] * 5,
        "pose": {"R": [1, 0, 0, 0, 1, 0, 0, 0, 1], "t": [0, 0, 0]},
        "conf": 0.123456789123456789,
    }
    message = face_message(result, 1)
    assert message["bbox"][2] > 0
    assert len(json.dumps(message).encode()) < 1024


def test_launcher_bounds_ws_queue_and_disables_compression(monkeypatch):
    from agemorph3d.__main__ import main

    calls = []
    monkeypatch.setattr(
        "agemorph3d.__main__.uvicorn.run", lambda *args, **kwargs: calls.append(kwargs)
    )
    main()
    assert calls[0]["ws_max_queue"] == 1
    assert calls[0]["ws_max_size"] == 2 * 1024**2
    assert calls[0]["ws_per_message_deflate"] is False

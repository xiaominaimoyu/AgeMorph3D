"""Explicit synthetic browser fixture, excluded from the installed backend package.

Run only with AGEMORPH_SYNTHETIC_AGING_CONTRACT=1. It never loads models, accepts
real portraits, changes production configuration or grants age-quality evidence.
"""

from __future__ import annotations

import asyncio
import io
import json
import math
import os
import re
from contextlib import asynccontextmanager
from types import SimpleNamespace

import numpy as np
from agemorph3d.aging_sessions import (
    AgingCoordinator,
    AgingSessionCache,
    SessionClosed,
    SessionNotFound,
    SessionResult,
    SessionSource,
)
from agemorph3d.config import Settings
from agemorph3d.errors import ApiError
from agemorph3d.middleware import LocalRequestMiddleware
from agemorph3d.schemas import AgingRequest
from agemorph3d.static_mesh import _encode_glb, build_static_mesh
from fastapi import FastAPI, Request
from PIL import Image
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response


def _windows_parent_monitor():
    """Watch a held parent handle; only this synthetic child exits when it signals."""
    import ctypes
    import threading
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x00100000, False, os.getppid())  # SYNCHRONIZE only.
    if not handle:
        raise RuntimeError("Cannot establish synthetic fixture parent ownership.")

    def watch():
        outcome = kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
        kernel32.CloseHandle(handle)
        os._exit(0 if outcome == 0 else 1)

    threading.Thread(target=watch, name="synthetic-fixture-parent", daemon=True).start()
    return True


def _start_parent_monitor():
    if (
        os.environ.get("AGEMORPH_SYNTHETIC_AGING_CONTRACT") != "1"
        or os.environ.get("AGEMORPH_SYNTHETIC_PARENT_MONITOR") != "1"
        or os.name != "nt"
    ):
        return False
    return _windows_parent_monitor()


def _png(array):
    stream = io.BytesIO()
    Image.fromarray(array).save(stream, "PNG")
    return stream.getvalue()


def _texture(age):
    rgba = np.zeros((8, 8, 4), dtype=np.uint8)
    rgba[2:7, 1:7] = [int(age * 3) % 256, 110, 170, 255]
    return SimpleNamespace(
        png=_png(rgba),
        gltf_uv=np.array([[0, 0], [0.5, 1], [1, 0]], dtype=np.float32),
        metadata={"kind": "synthetic_contract", "synthetic": True, "age_quality_accepted": False},
    )


class _LeasedResponse(Response):
    def __init__(self, data, media_type, lease):
        self._lease = lease
        super().__init__(data, media_type=media_type)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._lease.close()


def create_app() -> FastAPI:
    if os.environ.get("AGEMORPH_SYNTHETIC_AGING_CONTRACT") != "1":
        raise RuntimeError(
            "This test-only fixture requires the explicit synthetic contract marker."
        )
    nonce = os.environ.get("AGEMORPH_SYNTHETIC_NONCE", "")
    if not re.fullmatch(r"[a-f0-9]{48}", nonce):
        raise RuntimeError("The synthetic fixture requires its owning runner's random nonce.")
    parent_monitor_enabled = _start_parent_monitor()
    origin = os.environ.get("AGEMORPH_SYNTHETIC_FRONTEND", "http://127.0.0.1:5177")
    settings = Settings(allowed_origins=(origin,), max_image_bytes=64 * 1024)
    now, gate = [100.0], asyncio.Event()
    gate.set()
    state = {"calls": [], "processing": 0, "completed": 0}
    cache = AgingSessionCache(ttl_seconds=300, max_entries=16, clock=lambda: now[0])
    age = {"value": 42.5, "method": "user", "calibration_id": None}
    rgb = np.full((16, 16, 3), [10, 20, 30], dtype=np.uint8)
    upload_png = _png(rgb)
    raw = SimpleNamespace(
        shape=np.zeros(40, dtype=np.float32),
        expr=np.zeros(10, dtype=np.float32),
        vertices=np.array([[-1, -1, 0], [0, 1, 1], [1, -1, 0]], dtype=np.float32),
        triangles=np.array([[0, 1, 2]], dtype=np.int64),
        projection=np.column_stack((np.eye(3), [12, 12, 0])),
        roi=(0, 0, 24, 24),
        coordinate_system="bfm_model_raw",
        topology_sha256="a" * 64,
    )
    base = build_static_mesh(raw, age, texture=_texture(42.5))
    original = SessionSource(
        source_age_json=json.dumps(age).encode(),
        original_rgb=rgb.tobytes(),
        aligned_png=upload_png,
        correspondence=json.dumps(
            {
                "kind": "synthetic_contract",
                "topology_sha256": "a" * 64,
                "source_size": [16, 16],
                "aligned_size": [16, 16],
            }
        ).encode(),
        glb=base.glb,
        texture_png=_texture(42.5).png,
        shape=tuple(raw.shape.tolist()),
    )

    async def processor(source, target_age):
        assert source is original
        state["calls"].append(target_age)
        state["processing"] += 1
        try:
            await gate.wait()
            texture = _texture(target_age)
            extras = {
                "synthetic": True,
                "kind": "synthetic_contract",
                "source_age": age,
                "asset_mode": "static",
                "coordinate_metadata": base.coordinate_metadata,
                "topology_id": base.topology_id,
                "requested_age": target_age,
                "age_quality_accepted": False,
                "identity_quality_accepted": False,
            }
            glb = _encode_glb(base.vertices, base.normals, base.triangles, extras, texture)
            return SessionResult(glb, texture.png, source.shape, "synthetic_contract")
        finally:
            state["processing"] -= 1
            state["completed"] += 1

    coordinator = AgingCoordinator(cache, processor)

    @asynccontextmanager
    async def lifespan(_app):
        await coordinator.start()
        try:
            yield
        finally:
            gate.set()
            await coordinator.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.synthetic_only = True
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )
    app.add_middleware(LocalRequestMiddleware, settings=settings)

    @app.exception_handler(ApiError)
    async def api_error(_request, error):
        return JSONResponse(
            {"code": error.code, "detail": error.detail}, status_code=error.status_code
        )

    @app.exception_handler(Exception)
    async def safe_error(_request, _error):
        return JSONResponse(
            {"code": "SYNTHETIC_CONTRACT_FAILED", "detail": "合成契约检查失败。"}, status_code=500
        )

    @app.post("/_contract/setup")
    async def setup():
        return {
            "synthetic_only": True,
            "source_age": age,
            "sam_inference": False,
            "g3_accepted": False,
            "input_path": "/_contract/input.png",
        }

    @app.get("/_contract/input.png")
    async def input_png():
        return Response(upload_png, media_type="image/png")

    @app.get("/_contract/state")
    async def current_state():
        return {
            **state,
            "cache": cache.stats,
            "synthetic_only": True,
            "fixture_pid": os.getpid(),
            "fixture_ppid": os.getppid(),
            "fixture_nonce": nonce,
            "parent_monitor_enabled": parent_monitor_enabled,
        }

    @app.post("/_contract/block")
    async def block():
        gate.clear()
        return {"blocked": True}

    @app.post("/_contract/release")
    async def release():
        gate.set()
        return {"blocked": False}

    @app.post("/_contract/advance")
    async def advance(request: Request):
        payload = await request.json()
        seconds = payload.get("seconds")
        if (
            type(seconds) not in {int, float}
            or not math.isfinite(seconds)
            or not 0 <= seconds <= 1000
        ):
            raise ApiError(422, "BAD_INPUT", "合成时钟增量无效。")
        now[0] += seconds
        cache.sweep()
        return {"synthetic_clock": now[0], "cache": cache.stats}

    @app.get("/api/health")
    async def health():
        return {
            "api_version": "1.2",
            "version": "synthetic-contract",
            "device": "synthetic",
            "models": {
                "age_texture": {
                    "state": "ready",
                    "backend": "synthetic_contract",
                    "provider": "synthetic",
                    "detail": "Only this test fixture is ready.",
                }
            },
            "capabilities": {
                "reconstruction": True,
                "realtime": False,
                "age_morph": False,
                "age_texture": True,
            },
            "synthetic_only": True,
        }

    @app.post("/api/reconstruct")
    async def reconstruct(request: Request):
        async with request.form(max_files=1, max_fields=1) as form:
            file = form.get("image")
            if (
                set(form) != {"image", "source_age"}
                or form.get("source_age") != "42.5"
                or not hasattr(file, "read")
                or await file.read(65537) != upload_png
            ):
                raise ApiError(
                    422, "SYNTHETIC_INPUT_REQUIRED", "此测试仅接受内置合成图片与42.5源龄。"
                )
        identifier = cache.publish(original)
        return {
            "mesh_id": identifier,
            "topology_id": base.topology_id,
            "asset_mode": "static",
            "capabilities": {"age_morph": False, "age_texture": True},
            "source_age": age,
            "shape": list(original.shape),
            "expr": raw.expr.tolist(),
            "pose": base.pose,
            "texture_url": f"/api/assets/{identifier}/base.png",
            "synthetic_only": True,
        }

    @app.post("/api/aging")
    async def aging(payload: AgingRequest, request: Request):
        async def disconnected():
            while True:
                if (await request.receive())["type"] == "http.disconnect":
                    return

        work = asyncio.create_task(
            coordinator.generate(payload.mesh_id, payload.age, timeout_seconds=5)
        )
        connection = asyncio.create_task(disconnected())
        try:
            await asyncio.wait({work, connection}, return_when=asyncio.FIRST_COMPLETED)
            if connection.done():
                raise ApiError(499, "CANCELLED", "合成请求已断开。")
            generated = work.result()
        finally:
            work.cancel()
            connection.cancel()
            await asyncio.gather(work, connection, return_exceptions=True)
        filename = (
            "base.png" if generated.kind == "source_reset" else f"age-{int(payload.age):03d}.png"
        )
        return {
            "shape_aged": list(generated.shape),
            "texture_url": f"/api/assets/{payload.mesh_id}/{filename}",
            "kind": generated.kind,
            "synthetic_only": True,
        }

    @app.get("/api/assets/{identifier}/{filename}")
    async def asset(identifier: str, filename: str):
        lease = None
        try:
            lease = cache.acquire(identifier)
            if filename == "mesh.glb":
                data, media_type = lease.source.glb, "model/gltf-binary"
            elif filename == "base.png":
                data, media_type = lease.source.texture_png, "image/png"
            elif match := re.fullmatch(r"age-([0-9]{3})\.png", filename):
                generated = cache.get_result(lease, int(match[1]))
                if generated is None:
                    raise ApiError(404, "ASSET_NOT_FOUND", "合成目标尚未生成。")
                data, media_type = generated.texture_png, "image/png"
            else:
                raise ApiError(404, "ASSET_NOT_FOUND", "合成资产不存在。")
            return _LeasedResponse(data, media_type, lease)
        except (SessionNotFound, SessionClosed):
            if lease is not None:
                lease.close()
            raise ApiError(404, "SESSION_EXPIRED", "合成会话已过期，请重新建立。") from None
        except BaseException:
            if lease is not None:
                lease.close()
            raise

    @app.get("/_contract/production-probe")
    async def production_probe():
        import httpx
        from agemorph3d.app import create_app as production_app

        production = production_app(Settings())
        async with production.router.lifespan_context(production):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=production), base_url="http://127.0.0.1"
            ) as client:
                response = await client.post(
                    "/api/aging", json={"mesh_id": "synthetic-probe", "age": 20}
                )
                flags = (await client.get("/api/health")).json()["capabilities"]
        return {
            "aging_status": response.status_code,
            "aging_code": response.json()["code"],
            "age_morph": flags["age_morph"],
            "age_texture": flags["age_texture"],
            "synthetic_only": True,
        }

    return app

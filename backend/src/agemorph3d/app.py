"""B1 service contract. Production never substitutes a synthetic reconstruction."""

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from . import __version__
from .config import Settings
from .errors import ApiError, ErrorResponse
from .images import decode_image
from .middleware import LocalRequestMiddleware, private_error_headers
from .runtime import Runtime, model_not_ready
from .schemas import AgingRequest, Health


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = Runtime()
        try:
            yield
        finally:
            await app.state.runtime.close()

    app = FastAPI(
        title="AgeMorph3D Local API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        responses={
            status: {"model": ErrorResponse}
            for status in (400, 403, 404, 413, 415, 422, 429, 500, 503, 504)
        },
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )
    app.add_middleware(LocalRequestMiddleware, settings=settings)

    @app.exception_handler(ApiError)
    async def api_error(_request: Request, exc: ApiError):
        headers = {"Retry-After": "1"} if exc.status_code == 429 else None
        return JSONResponse(
            {"detail": exc.detail, "code": exc.code},
            status_code=exc.status_code,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _exc: RequestValidationError):
        # Validation input and raw Pydantic errors can contain private photo/parameter data.
        return JSONResponse(
            {
                "detail": "请求字段格式无效，请检查模型标识和 20—70 岁目标年龄。",
                "code": "BAD_INPUT",
            },
            status_code=422,
        )

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "请求无法处理。"
        return JSONResponse({"detail": detail, "code": "BAD_INPUT"}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, _exc: Exception):
        return JSONResponse(
            {"detail": "本地处理失败，请稍后重试。", "code": "INTERNAL_ERROR"},
            status_code=500,
            headers=private_error_headers(request.scope, settings),
        )

    @app.get("/api/health", response_model=Health)
    async def health(request: Request):
        return request.app.state.runtime.health()

    @app.post(
        "/api/reconstruct",
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "required": ["image"],
                            "properties": {"image": {"type": "string", "format": "binary"}},
                        },
                    },
                },
            },
        },
    )
    async def reconstruct(request: Request):
        content_type = request.headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip().lower() != "multipart/form-data":
            raise ApiError(415, "BAD_INPUT", "请使用 multipart/form-data 的 image 字段上传图片。")
        parser = MultiPartParser(
            request.headers,
            request.stream(),
            max_files=1,
            max_fields=0,
            max_part_size=settings.max_image_bytes,
        )
        # Keep the original photo in a bounded memory spool, never a temporary disk file.
        parser.spool_max_size = settings.max_image_bytes + 64 * 1024
        try:
            form = await parser.parse()
        except (MultiPartException, ValueError) as exc:
            raise ApiError(400, "BAD_INPUT", "上传格式无效，只允许一个 image 图片字段。") from exc
        try:
            fields = form.multi_items()
            if len(fields) != 1 or fields[0][0] != "image" or not hasattr(fields[0][1], "read"):
                raise ApiError(422, "BAD_INPUT", "需要且只允许一个 image 图片文件。")
            upload = fields[0][1]
            data = await upload.read(settings.max_image_bytes + 1)

            def validate() -> None:
                with decode_image(data, upload.content_type or "", settings):
                    pass

            budget = request.state.http_deadline - asyncio.get_running_loop().time()
            if budget <= 0:
                raise ApiError(504, "TIMEOUT", "本地处理超时，请稍后重试。")
            await request.app.state.runtime.run(validate, budget)
            raise model_not_ready()
        finally:
            await form.close()

    @app.post("/api/aging")
    async def aging(_payload: AgingRequest):
        raise model_not_ready()

    @app.get("/api/assets/{mesh_id}/mesh.glb")
    async def mesh_asset(mesh_id: str):
        # No filesystem mount: assets only become available after B2/B3 publishes them.
        raise ApiError(404, "ASSET_NOT_FOUND", "模型资产不存在或已过期，请重新重建。")

    @app.websocket("/ws/frame")
    async def frame(socket: WebSocket):
        await socket.accept()
        await socket.send_json({"type": "status", "device": "cpu"})
        seq = 0
        try:
            while True:
                message = await socket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                seq += 1
                data = message.get("bytes")
                try:
                    if data is None:
                        raise ApiError(400, "BAD_INPUT", "实时帧必须为 JPEG 二进制数据。")

                    def validate_frame(frame_data: bytes = data) -> None:
                        with decode_image(frame_data, "image/jpeg", settings, frame=True):
                            pass

                    await socket.app.state.runtime.run(
                        validate_frame,
                        settings.frame_timeout_seconds,
                    )
                    raise model_not_ready()
                except ApiError as exc:
                    payload = json.dumps(
                        {"type": "error", "seq": seq, "code": exc.code, "msg": exc.detail},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    # Current fixed messages fit; never send an unbounded algorithm exception.
                    if len(payload.encode("utf-8")) > 1024:
                        payload = '{"type":"error","code":"BAD_INPUT","msg":"实时处理失败。"}'
                    await socket.send_text(payload)
                    await socket.close(code=1013 if exc.status_code in {429, 503, 504} else 1003)
                    return
                except Exception:
                    await socket.send_json(
                        {
                            "type": "error",
                            "seq": seq,
                            "code": "INTERNAL_ERROR",
                            "msg": "实时处理失败，请稍后重试。",
                        }
                    )
                    await socket.close(code=1011)
                    return
        except WebSocketDisconnect:
            return

    return app

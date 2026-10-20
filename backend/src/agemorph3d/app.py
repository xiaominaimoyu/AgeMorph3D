"""Local photo-to-static-GLB service with strict model readiness and bounded assets."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

from . import __version__
from .asset_cache import AssetLease
from .config import Settings
from .errors import ApiError, ErrorResponse
from .frame_socket import handle_frames
from .middleware import LocalRequestMiddleware, private_error_headers
from .runtime import Runtime, model_not_ready
from .schemas import AgingRequest, Health, Reconstruction, SourceAge


class MeshResponse(Response):
    """Pin immutable bytes until ASGI send finishes, including cancellation."""

    media_type = "model/gltf-binary"

    def __init__(self, lease: AssetLease):
        self._lease = lease
        super().__init__(content=lease.data, media_type=self.media_type)

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._lease.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.runtime = Runtime(settings)
        try:
            await app.state.runtime.start()
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
        response_model=Reconstruction,
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "required": ["image"],
                            "properties": {
                                "image": {"type": "string", "format": "binary"},
                                "source_age": {
                                    "type": "string",
                                    "pattern": r"^[0-9]+(?:\.[0-9]+)?$",
                                    "maxLength": 32,
                                    "description": (
                                        "Optional user source age, 20–70; omitted means unknown."
                                    ),
                                },
                            },
                            "additionalProperties": False,
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
            max_fields=1,
            max_part_size=settings.max_image_bytes,
        )
        # Keep the original photo in a bounded memory spool, never a temporary disk file.
        parser.spool_max_size = settings.max_image_bytes + 64 * 1024
        try:
            form = await parser.parse()
        except (MultiPartException, ValueError) as exc:
            raise ApiError(
                400, "BAD_INPUT", "上传格式无效，只允许 image 和可选 source_age 字段。"
            ) from exc
        try:
            fields = form.multi_items()
            if any(name not in {"image", "source_age"} for name, _ in fields):
                raise ApiError(
                    422 if len(fields) == 1 else 400, "BAD_INPUT", "上传包含不支持的字段。"
                )
            images = [value for name, value in fields if name == "image"]
            if len(images) != 1:
                raise ApiError(422, "BAD_INPUT", "需要且只允许一个 image 图片文件。")
            upload = images[0]
            if not hasattr(upload, "read"):
                raise ApiError(400, "BAD_INPUT", "image 字段必须为图片文件。")
            ages = [value for name, value in fields if name == "source_age"]
            try:
                source_age = SourceAge.from_form(ages[0] if ages else None)
            except ValueError as exc:
                raise ApiError(422, "BAD_INPUT", "源年龄必须为 20—70 岁的十进制数值。") from exc
            data = await upload.read(settings.max_image_bytes + 1)

            budget = request.state.http_deadline - asyncio.get_running_loop().time()
            if budget <= 0:
                raise ApiError(504, "TIMEOUT", "本地处理超时，请稍后重试。")
            runtime = request.app.state.runtime

            async def disconnected() -> None:
                # The bounded middleware/form parser consumed the complete body.
                while True:
                    message = await request.receive()
                    if message["type"] == "http.disconnect":
                        return

            work = asyncio.create_task(
                runtime.prepare_static(data, upload.content_type or "", source_age, budget)
            )
            connection = asyncio.create_task(disconnected())
            try:
                await asyncio.wait({work, connection}, return_when=asyncio.FIRST_COMPLETED)
                if connection.done():
                    # Cancelling the waiter leaves the actual worker's slot occupied.
                    raise ApiError(499, "CANCELLED", "请求连接已断开，请重新提交。")
                prepared = work.result()
                if asyncio.get_running_loop().time() >= request.state.http_deadline:
                    raise ApiError(504, "TIMEOUT", "本地处理超时，请稍后重试。")
                # Publication happens only on the event loop after successful waiting.
                return runtime.publish_static(prepared)
            finally:
                work.cancel()
                connection.cancel()
                await asyncio.gather(work, connection, return_exceptions=True)
        finally:
            await form.close()

    @app.post("/api/aging")
    async def aging(_payload: AgingRequest):
        raise model_not_ready()

    @app.get("/api/assets/{mesh_id}/mesh.glb")
    async def mesh_asset(mesh_id: str, request: Request):
        return MeshResponse(request.app.state.runtime.acquire_mesh(mesh_id))

    @app.websocket("/ws/frame")
    async def frame(socket: WebSocket):
        await handle_frames(socket, settings)

    return app

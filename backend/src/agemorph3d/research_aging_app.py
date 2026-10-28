"""Private research HTTP adapter; models and native work are owned by its service.

This factory exposes no production routes, loads no model, and grants no model
readiness or quality capability. Raw photographs and reviewed PNGs stay in memory.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated, Literal, TypeVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response

from .config import Settings
from .errors import ApiError
from .middleware import LocalRequestMiddleware, private_error_headers
from .research_aging_pipeline import ReviewRequired, TargetMaskReview
from .research_aging_service import PUBLICATION_GUARD
from .schemas import SourceAge

if TYPE_CHECKING:
    from .research_aging_service import ResearchAgingService

_T = TypeVar("_T")
_ID = re.compile(r"[0-9a-f]{32}")
_CONDITION = re.compile(r"(?:[2-6][0-9]|70)")
_MAX_JSON_BYTES = 16 * 1024
_MAX_REVIEW_BYTES = 12 * 1024**2
_MAX_MASK_BYTES = 4 * 1024**2
_MAX_B64_CHARS = 4 * ((_MAX_MASK_BYTES + 2) // 3)
_FLAGS = {
    "research_only": True,
    "service_ready": False,
    "production_enabled": False,
    "g3_complete": False,
    "quality_accepted": False,
    "age_quality_accepted": False,
    "age_texture_quality_accepted": False,
    "identity_quality_accepted": False,
    "visual_seam_quality_accepted": False,
    "years_calibrated": False,
    "human_review_completed": False,
}
_SAFE_CODES = {
    "BAD_INPUT",
    "ORIGIN_DENIED",
    "INPUT_TOO_LARGE",
    "PAYLOAD_TOO_LARGE",
    "UNSUPPORTED_MEDIA_TYPE",
    "SOURCE_AGE_REQUIRED",
    "INTEGER_AGE_REQUIRED",
    "SESSION_EXPIRED",
    "STAGE_EXPIRED",
    "RESULT_NOT_FOUND",
    "RESULT_CONFLICT",
    "REVIEW_REQUIRED",
    "INVALID_CONTEXT",
    "NO_FACE",
    "MULTI_FACE",
    "RECONSTRUCTION_FAILED",
    "REGISTRATION_FAILED",
    "BUSY",
    "TIMEOUT",
    "CANCELLED",
    "MODEL_NOT_READY",
    "WORKER_CLOSED",
    "WORKER_PROTOCOL",
    "WORKER_FAILED",
    "INTERNAL_ERROR",
}
_DETAILS = {
    400: "请求内容无效。",
    403: "仅允许配置的本机页面访问此研究服务。",
    404: "研究会话或资产不存在或已过期。",
    409: "生成目标需要匹配图像和拟合指纹的审核遮罩。",
    413: "请求内容超过大小限制。",
    415: "请求媒体类型不受支持。",
    422: "请求字段或年龄条件无效。",
    429: "本机研究资源正忙，请稍后重试。",
    499: "请求连接已断开。",
    500: "本机研究处理失败。",
    503: "研究处理资源当前不可用。",
    504: "本机研究请求超时。",
}


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ConditionBody(_Body):
    condition: Annotated[int, Field(strict=True, ge=20, le=70)]


class _AbsoluteBody(_Body):
    age: Annotated[float, Field(strict=True, allow_inf_nan=False, ge=20, le=70)]


_Sha = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
_Text = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
_EncodedMask = Annotated[str, Field(strict=True, min_length=1, max_length=_MAX_B64_CHARS)]


class _ReviewBody(_Body):
    source_fingerprint: _Sha
    generated_sha256: _Sha
    fit_sha256: _Sha
    allowed_png_b64: _EncodedMask
    occluded_png_b64: _EncodedMask
    reviewer: _Text
    method: _Text
    version: _Text
    reviewer_kind: Literal["ai", "human"]


class _LeasedResponse(Response):
    """Keep the service's download/source lease through ASGI send or cancellation."""

    def __init__(self, lease, media_type: str):
        self._lease = lease
        try:
            super().__init__(content=lease.data, media_type=media_type)
        except BaseException:
            lease.close()
            raise

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._lease.close()


def _identifier(value: str, *, stage=False) -> str:
    if _ID.fullmatch(value) is None:
        raise ApiError(404, "STAGE_EXPIRED" if stage else "SESSION_EXPIRED", _DETAILS[404])
    return value


def _condition_path(value: str) -> int:
    if _CONDITION.fullmatch(value) is None:
        raise ApiError(422, "INTEGER_AGE_REQUIRED", _DETAILS[422])
    return int(value)


def _media_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def _consume(task: asyncio.Task) -> None:
    if not task.cancelled():
        task.exception()


async def _connected(
    request: Request, operation: Callable[[float], Awaitable[_T]], settings: Settings
) -> _T:
    """Cancel only the public waiter; the service retains its actual native job."""
    loop = asyncio.get_running_loop()
    deadline = getattr(request.state, "http_deadline", loop.time() + settings.http_timeout_seconds)
    budget = deadline - loop.time()
    if budget <= 0:
        raise ApiError(504, "TIMEOUT", _DETAILS[504])

    async def disconnected():
        while True:
            message = await request.receive()
            if message["type"] == "http.disconnect":
                return

    parent = asyncio.current_task()
    connection = asyncio.create_task(disconnected())
    connection.add_done_callback(_consume)
    work = None

    def publication_guard():
        # The connection receiver can finish before asyncio.wait wakes this
        # caller. Check at the actual cache write too, not only after waiting.
        if connection.done() or parent is not None and parent.cancelling():
            raise ApiError(499, "CANCELLED", _DETAILS[499])
        if loop.time() >= deadline:
            raise ApiError(504, "TIMEOUT", _DETAILS[504])

    try:
        token = PUBLICATION_GUARD.set(publication_guard)
        try:
            work = asyncio.create_task(operation(budget))
        finally:
            # Only operation descendants inherit this request's publication
            # boundary. Concurrent requests keep their own ContextVar values.
            PUBLICATION_GUARD.reset(token)
        work.add_done_callback(_consume)
        done, _pending = await asyncio.wait(
            {work, connection}, timeout=budget, return_when=asyncio.FIRST_COMPLETED
        )
        if connection in done:
            connection.result()
            raise ApiError(499, "CANCELLED", _DETAILS[499])
        if work not in done or loop.time() >= deadline:
            raise ApiError(504, "TIMEOUT", _DETAILS[504])
        return work.result()
    finally:
        # Awaiting a draining service waiter here would delay the HTTP timeout.
        # Its owned native task and source lease remain under service admission.
        if work is not None:
            work.cancel()
        connection.cancel()


async def _json_body(request: Request, model: type[_Body], *, review=False):
    if _media_type(request) != "application/json":
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", _DETAILS[415])
    raw = await request.body()
    if len(raw) > (_MAX_REVIEW_BYTES if review else _MAX_JSON_BYTES):
        raise ApiError(413, "PAYLOAD_TOO_LARGE", _DETAILS[413])

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON field")
            value[key] = item
        return value

    def nonfinite(_constant):
        raise ValueError("Nonfinite JSON constant")

    try:
        payload = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
        return model.model_validate(payload)
    except (ValueError, UnicodeError, RecursionError, OverflowError, ValidationError) as error:
        raise ApiError(422, "BAD_INPUT", _DETAILS[422]) from error


def _decode_mask(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ApiError(422, "BAD_INPUT", _DETAILS[422]) from error
    if not 0 < len(decoded) <= _MAX_MASK_BYTES or base64.b64encode(decoded).decode() != value:
        raise ApiError(422, "BAD_INPUT", _DETAILS[422])
    return decoded


def _source_urls(sid: str) -> dict:
    return {
        "source_glb_url": f"/research/sessions/{sid}/source.glb",
        "source_texture_url": f"/research/sessions/{sid}/source-texture.png",
    }


def _stage_urls(sid: str, staged) -> dict:
    prefix = f"/research/sessions/{sid}/stages/{staged.stage_id}"
    return {
        "staged": asdict(staged),
        "preview_url": prefix + "/preview.png",
        "fit_url": prefix + "/fit.json",
    }


def _result_urls(sid: str, kind: str, condition: int | None = None) -> dict:
    if kind == "source_reset":
        urls = _source_urls(sid)
        return {"mesh_url": urls["source_glb_url"], "texture_url": urls["source_texture_url"]}
    if type(condition) is not int or not 20 <= condition <= 70:
        raise ApiError(500, "INTERNAL_ERROR", _DETAILS[500])
    prefix = f"/research/sessions/{sid}/conditions/{condition}"
    return {"mesh_url": prefix + "/mesh.glb", "texture_url": prefix + "/texture.png"}


def create_research_app(service: ResearchAgingService, settings: Settings | None = None) -> FastAPI:
    """Inject an already configured research owner; never construct/load models here."""
    settings = settings or Settings(max_json_bytes=_MAX_REVIEW_BYTES, http_timeout_seconds=180)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            await service.start()
            yield
        finally:
            await service.close()

    app = FastAPI(
        title="AgeMorph3D Private Research API",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.research_service = service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )
    app.add_middleware(LocalRequestMiddleware, settings=settings)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError):
        status = error.status_code if error.status_code in _DETAILS else 500
        payload = {
            "code": error.code if error.code in _SAFE_CODES else "INTERNAL_ERROR",
            "detail": (
                "相同条件已有不同注册结果，请新建研究会话。"
                if error.code == "RESULT_CONFLICT"
                else _DETAILS[status]
            ),
        }
        if isinstance(error, ReviewRequired):
            sid = request.path_params.get("sid", "")
            if _ID.fullmatch(sid):
                payload.update(_stage_urls(sid, error.staged))
        headers = private_error_headers(request.scope, settings)
        if status == 429:
            headers["Retry-After"] = "1"
        return JSONResponse(payload, status_code=status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _error: RequestValidationError):
        return JSONResponse(
            {"code": "BAD_INPUT", "detail": _DETAILS[422]},
            status_code=422,
            headers=private_error_headers(request.scope, settings),
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        status = error.status_code
        return JSONResponse(
            {"code": "BAD_INPUT", "detail": _DETAILS.get(status, "请求无法处理。")},
            status_code=status,
            headers=private_error_headers(request.scope, settings),
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, _error: Exception):
        return JSONResponse(
            {"code": "INTERNAL_ERROR", "detail": _DETAILS[500]},
            status_code=500,
            headers=private_error_headers(request.scope, settings),
        )

    @app.get("/research/health")
    async def health():
        return {
            "service": service.snapshot(),
            "capabilities": {
                "reconstruction": False,
                "age_morph": False,
                "age_texture": False,
                "realtime": False,
            },
            **_FLAGS,
        }

    @app.post("/research/sessions")
    async def create_session(request: Request):
        if any(key != "source_age" for key in request.query_params):
            raise ApiError(422, "BAD_INPUT", _DETAILS[422])
        ages = request.query_params.getlist("source_age")
        if len(ages) > 1:
            raise ApiError(422, "BAD_INPUT", _DETAILS[422])
        try:
            source_age = SourceAge.from_form(ages[0] if ages else None)
        except ValueError as error:
            raise ApiError(422, "BAD_INPUT", _DETAILS[422]) from error
        media = _media_type(request)
        if media not in {"image/jpeg", "image/png", "image/webp"}:
            raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", _DETAILS[415])
        photo = await request.body()
        if not photo:
            raise ApiError(400, "BAD_INPUT", _DETAILS[400])
        if len(photo) > settings.max_image_bytes:
            raise ApiError(413, "INPUT_TOO_LARGE", _DETAILS[413])
        sid = await _connected(
            request,
            lambda budget: service.create(photo, media, source_age, timeout_seconds=budget),
            settings,
        )
        return {**service.source_info(sid), **_source_urls(sid), **_FLAGS}

    @app.post("/research/sessions/{sid}/conditions")
    async def stage_condition(sid: str, request: Request):
        _identifier(sid)
        payload = await _json_body(request, _ConditionBody)
        staged = await _connected(
            request,
            lambda budget: service.stage(sid, payload.condition, timeout_seconds=budget),
            settings,
        )
        return {**_stage_urls(sid, staged), **_FLAGS}

    @app.get("/research/sessions/{sid}")
    async def session_info(sid: str):
        _identifier(sid)
        return {**service.source_info(sid), **_source_urls(sid), **_FLAGS}

    @app.get("/research/sessions/{sid}/stages/{stageid}/status")
    async def stage_status(sid: str, stageid: str):
        _identifier(sid)
        _identifier(stageid, stage=True)
        staged = service.check_stage(sid, stageid)
        return {
            **_stage_urls(sid, staged),
            "status": "available",
            "ttl_extended": False,
            "reservation_held": False,
            **_FLAGS,
        }

    @app.get("/research/sessions/{sid}/stages/{stageid}/preview.png")
    async def staged_preview(sid: str, stageid: str):
        _identifier(sid)
        _identifier(stageid, stage=True)
        return _LeasedResponse(service.asset(sid, "preview", condition=stageid), "image/png")

    @app.get("/research/sessions/{sid}/stages/{stageid}/fit.json")
    async def staged_fit(sid: str, stageid: str):
        _identifier(sid)
        _identifier(stageid, stage=True)
        return _LeasedResponse(service.asset(sid, "fit", condition=stageid), "application/json")

    @app.post("/research/sessions/{sid}/stages/{stageid}/reviews")
    async def reviewed_registration(sid: str, stageid: str, request: Request):
        _identifier(sid)
        _identifier(stageid, stage=True)
        payload = await _json_body(request, _ReviewBody, review=True)
        try:
            review = TargetMaskReview(
                payload.source_fingerprint,
                payload.generated_sha256,
                payload.fit_sha256,
                _decode_mask(payload.allowed_png_b64),
                _decode_mask(payload.occluded_png_b64),
                payload.reviewer,
                payload.method,
                payload.version,
                payload.reviewer_kind,
            )
        except ValueError as error:
            raise ApiError(422, "BAD_INPUT", _DETAILS[422]) from error
        registered = await _connected(
            request,
            lambda budget: service.register(sid, stageid, review, timeout_seconds=budget),
            settings,
        )
        provenance = json.loads(registered.provenance_json)
        condition = provenance["target_condition"]
        result = registered.result
        return {
            "session_id": sid,
            "kind": result.kind,
            "shape": list(result.shape),
            "source_age": service.source_info(sid)["source_age"],
            "condition": condition,
            "provenance": provenance,
            "provenance_json_b64": base64.b64encode(registered.provenance_json).decode("ascii"),
            **_result_urls(sid, result.kind, condition),
            **_FLAGS,
        }

    @app.post("/research/sessions/{sid}/absolute")
    async def absolute_age(sid: str, request: Request):
        _identifier(sid)
        payload = await _json_body(request, _AbsoluteBody)
        result = await _connected(
            request,
            lambda budget: service.absolute(sid, payload.age, timeout_seconds=budget),
            settings,
        )
        condition = None if result.kind == "source_reset" else int(payload.age)
        return {
            "session_id": sid,
            "kind": result.kind,
            "shape": list(result.shape),
            "source_age": service.source_info(sid)["source_age"],
            **_result_urls(sid, result.kind, condition),
            **_FLAGS,
        }

    @app.get("/research/sessions/{sid}/source.glb")
    async def source_mesh(sid: str):
        _identifier(sid)
        return _LeasedResponse(service.asset(sid, "source_glb"), "model/gltf-binary")

    @app.get("/research/sessions/{sid}/source-texture.png")
    async def source_texture(sid: str):
        _identifier(sid)
        return _LeasedResponse(service.asset(sid, "source_texture"), "image/png")

    @app.get("/research/sessions/{sid}/conditions/{condition}/mesh.glb")
    async def registered_mesh(sid: str, condition: str):
        _identifier(sid)
        return _LeasedResponse(
            service.asset(sid, "glb", condition=_condition_path(condition)), "model/gltf-binary"
        )

    @app.get("/research/sessions/{sid}/conditions/{condition}/texture.png")
    async def registered_texture(sid: str, condition: str):
        _identifier(sid)
        return _LeasedResponse(
            service.asset(sid, "texture", condition=_condition_path(condition)), "image/png"
        )

    return app

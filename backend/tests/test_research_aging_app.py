"""Synthetic HTTP boundaries only; no models, real GLBs, files, or network IO.

The fake owns a controlled native task so ASGI disconnect/timeout checks can
distinguish cancellation of the HTTP waiter from cancellation of native work.
Real processor resources and image semantics have separate service/model probes.
"""

import asyncio
import base64
import json
from dataclasses import replace

import httpx
import pytest
from agemorph3d.aging_sessions import SessionResult
from agemorph3d.config import Settings
from agemorph3d.errors import ApiError
from agemorph3d.research_aging_app import create_research_app
from agemorph3d.research_aging_pipeline import (
    RegisteredConditionResult,
    ReviewRequired,
    StagedTarget,
)
from agemorph3d.schemas import SourceAge

SID = "a" * 32
STAGED = StagedTarget("b" * 32, "c" * 64, 45, "d" * 64, "e" * 64)
BASE = "/research/sessions/" + SID
REVIEW_URL = BASE + "/stages/" + STAGED.stage_id + "/reviews"
UNKNOWN = {"value": None, "method": "unknown", "calibration_id": None}
_MAX_MASK_BYTES = 4 * 1024**2


class SyntheticLease:
    def __init__(self, owner, data):
        self.owner, self.data = owner, data
        self.closed = False

    def close(self):
        if not self.closed:
            self.closed = True
            self.owner.downloads -= 1
            self.owner.releases += 1


class SyntheticService:
    """Transport-shaped fake; its byte assets deliberately do not claim valid GLB."""

    def __init__(self, *, block_create=False):
        self.started, self.closed, self.created = False, False, False
        self.age = SourceAge.model_validate(UNKNOWN)
        self.stage_calls, self.register_calls = [], []
        self.registered = False
        self.downloads = self.releases = 0
        self.block_create = block_create
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.waiter_cancelled = asyncio.Event()
        self.native = None
        self.last_review = None

    async def start(self):
        self.started = True

    async def close(self):
        self.closed = True
        self.release.set()
        if self.native is not None:
            await asyncio.gather(self.native, return_exceptions=True)

    def snapshot(self):
        return {"synthetic": True, "closed": self.closed, "downloads": self.downloads}

    async def create(self, image, content_type, source_age, timeout_seconds=180):
        assert isinstance(image, bytes) and timeout_seconds > 0
        assert content_type in {"image/jpeg", "image/png", "image/webp"}
        self.age = source_age
        if self.block_create:

            async def controlled_native():
                self.entered.set()
                await self.release.wait()
                return SID

            self.native = asyncio.create_task(controlled_native())
            try:
                await asyncio.shield(self.native)
            except asyncio.CancelledError:
                self.waiter_cancelled.set()
                raise
        self.created = True
        return SID

    def _source(self, session_id):
        if session_id != SID or not self.created:
            raise ApiError(404, "SESSION_EXPIRED", "private source detail")

    def source_info(self, session_id):
        self._source(session_id)
        return {
            "session_id": SID,
            "source_age": self.age.model_dump(),
            "source_fingerprint": STAGED.source_fingerprint,
            "shape": [0.0] * 40,
        }

    async def stage(self, session_id, condition, timeout_seconds=180):
        self._source(session_id)
        self.stage_calls.append(condition)
        return replace(STAGED, target_condition=condition)

    async def absolute(self, session_id, age, timeout_seconds=180):
        self._source(session_id)
        if self.age.value is None:
            raise ApiError(422, "SOURCE_AGE_REQUIRED", "unknown private age detail")
        if age == self.age.value:
            return SessionResult(
                b"synthetic source GLB", b"synthetic source PNG", (0.0,) * 40, "source_reset"
            )
        if not float(age).is_integer():
            raise ApiError(422, "INTEGER_AGE_REQUIRED", "private fractional-age detail")
        if age == 46:
            raise RuntimeError("PRIVATE_PHOTO_PATH_AND_TOKEN_123")
        if self.registered:
            return SessionResult(
                b"synthetic registered GLB", b"synthetic texture", (0.0,) * 40, "sam_registered_uv"
            )
        raise ReviewRequired(STAGED)

    async def register(self, session_id, stage_id, review, timeout_seconds=180):
        self._source(session_id)
        self.register_calls.append(review)
        if stage_id != STAGED.stage_id or (
            review.source_fingerprint,
            review.generated_sha256,
            review.fit_sha256,
        ) != (STAGED.source_fingerprint, STAGED.generated_sha256, STAGED.fit_sha256):
            raise ReviewRequired(STAGED)
        self.last_review, self.registered = review, True
        result = SessionResult(
            b"synthetic registered GLB", b"synthetic texture", (0.0,) * 40, "sam_registered_uv"
        )
        return RegisteredConditionResult(result, b'{"target_condition":45,"research_only":true}')

    def asset(self, session_id, kind, condition=None):
        self._source(session_id)
        if kind in {"glb", "texture"} and not self.registered:
            raise ApiError(404, "RESULT_NOT_FOUND", "private result detail")
        if kind in {"preview", "fit"} and condition != STAGED.stage_id:
            raise ApiError(404, "STAGE_EXPIRED", "private stage detail")
        self.downloads += 1
        return SyntheticLease(
            self,
            b'{"synthetic":true}' if kind == "fit" else b"synthetic asset, not a real image or GLB",
        )


def review_json(**changes):
    value = {
        "source_fingerprint": STAGED.source_fingerprint,
        "generated_sha256": STAGED.generated_sha256,
        "fit_sha256": STAGED.fit_sha256,
        "allowed_png_b64": base64.b64encode(b"synthetic mask transport bytes").decode(),
        "occluded_png_b64": base64.b64encode(b"synthetic excluded transport bytes").decode(),
        "reviewer": "synthetic tester",
        "method": "transport contract only",
        "version": "synthetic-v1",
        "reviewer_kind": "ai",
    }
    value.update(changes)
    return value


@pytest.fixture
async def client():
    service = SyntheticService()
    app = create_research_app(service)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http:
            yield http, service
    assert service.started and service.closed and service.downloads == 0


async def create(http, age="42.5"):
    suffix = "" if age is None else "?source_age=" + age
    response = await http.post(
        "/research/sessions" + suffix,
        content=b"synthetic photo bytes",
        headers={"Content-Type": "image/jpeg"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "outside.invalid"},
        {"Host": "127.0.0.1@outside.invalid"},
        {"Origin": "https://outside.invalid"},
        {"Origin": "null"},
    ],
)
async def test_untrusted_host_or_origin_is_rejected_with_private_headers(client, headers):
    http, _ = client
    response = await http.get("/research/health", headers=headers)
    assert response.status_code == 403 and response.json()["code"] == "ORIGIN_DENIED"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    if "Origin" in headers:
        assert "access-control-allow-origin" not in response.headers


async def test_health_cors_and_lifespan_keep_all_capabilities_closed(client):
    http, service = client
    response = await http.get("/research/health", headers={"Origin": "http://127.0.0.1:5173"})
    data = response.json()
    assert service.started and data["service"]["synthetic"]
    assert data["research_only"] is True
    assert not any(
        data[key]
        for key in (
            "service_ready",
            "production_enabled",
            "g3_complete",
            "quality_accepted",
            "human_review_completed",
        )
    )
    assert not any(data["capabilities"].values())
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "age,expected",
    [
        (None, UNKNOWN),
        ("42.5", {"value": 42.5, "method": "user", "calibration_id": None}),
        ("21", {"value": 21.0, "method": "user", "calibration_id": None}),
    ],
)
async def test_raw_photo_source_age_is_optional_and_never_inferred(client, age, expected):
    http, service = client
    data = await create(http, age)
    assert data["source_age"] == expected == service.age.model_dump()
    assert data["source_glb_url"] == BASE + "/source.glb"
    assert data["source_texture_url"] == BASE + "/source-texture.png"


@pytest.mark.parametrize(
    "query",
    [
        "?source_age=21&source_age=22",
        "?source_age=",
        "?source_age=true",
        "?source_age=21e0",
        "?source_age=19",
        "?source_age=71",
        "?source_age=nan",
        "?source_age=21&extra=1",
    ],
)
async def test_source_age_query_is_strict_and_rejects_duplicates(client, query):
    http, service = client
    response = await http.post(
        "/research/sessions" + query,
        content=b"synthetic photo",
        headers={"Content-Type": "image/png"},
    )
    assert response.status_code == 422 and not service.created


@pytest.mark.parametrize("media", ["application/json", "multipart/form-data", "text/plain", ""])
async def test_raw_photo_requires_supported_image_media_type(client, media):
    http, service = client
    response = await http.post(
        "/research/sessions", content=b"synthetic photo", headers={"Content-Type": media}
    )
    assert response.status_code == 415 and not service.created


@pytest.mark.parametrize(
    "payload",
    [
        {"condition": True},
        {"condition": 45.0},
        {"condition": "45"},
        {"condition": 19},
        {"condition": 71},
        {"condition": 45, "extra": "private"},
        {},
        [],
    ],
)
async def test_small_condition_json_is_strict_and_does_not_reach_service(client, payload):
    http, service = client
    await create(http)
    response = await http.post(BASE + "/conditions", json=payload)
    assert response.status_code == 422 and service.stage_calls == []


@pytest.mark.parametrize(
    "body", [b'{"condition":45,"condition":70}', b'{"condition":NaN}', b"null", b'{"condition":']
)
async def test_duplicate_nonfinite_or_invalid_json_never_reaches_service(client, body):
    http, service = client
    await create(http)
    response = await http.post(
        BASE + "/conditions", content=body, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422 and not service.stage_calls


async def test_small_json_has_16kib_budget_before_json_parsing(client):
    http, service = client
    await create(http)
    response = await http.post(
        BASE + "/conditions",
        content=b" " * (16 * 1024 + 1),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413 and response.json()["code"] == "PAYLOAD_TOO_LARGE"
    assert not service.stage_calls


async def test_stage_and_review_required_return_same_bound_preview_envelope(client):
    http, _ = client
    await create(http)
    staged = await http.post(BASE + "/conditions", json={"condition": 45})
    missing = await http.post(BASE + "/absolute", json={"age": 45})
    assert staged.status_code == 200 and missing.status_code == 409
    assert missing.json()["code"] == "REVIEW_REQUIRED"
    for key in ("staged", "preview_url", "fit_url"):
        assert staged.json()[key] == missing.json()[key]
    assert missing.json()["staged"]["fit_sha256"] == STAGED.fit_sha256


@pytest.mark.parametrize("field", ["source_fingerprint", "generated_sha256", "fit_sha256"])
async def test_review_three_fingerprints_cannot_be_reassigned(client, field):
    http, service = client
    await create(http)
    response = await http.post(REVIEW_URL, json=review_json(**{field: "f" * 64}))
    assert response.status_code == 409 and response.json()["code"] == "REVIEW_REQUIRED"
    assert not service.registered


@pytest.mark.parametrize(
    "changes",
    [
        {"allowed_png_b64": "%%%"},
        {"occluded_png_b64": ""},
        {"allowed_png_b64": "Zg==\n"},
        {"allowed_png_b64": "Zh=="},
        {"source_fingerprint": "C" * 64},
        {"fit_sha256": "e" * 63},
        {"reviewer_kind": "automatic"},
        {"reviewer": " "},
        {"extra": "private"},
    ],
)
async def test_review_encoding_and_metadata_are_strict(client, changes):
    http, service = client
    await create(http)
    response = await http.post(REVIEW_URL, json=review_json(**changes))
    assert response.status_code == 422 and service.register_calls == []


async def test_decoded_mask_limit_is_enforced_even_when_base64_length_still_fits(client):
    http, service = client
    await create(http)
    exact = b"x" * _MAX_MASK_BYTES
    larger = exact + b"x"
    assert len(base64.b64encode(exact)) == len(base64.b64encode(larger))
    rejected = await http.post(
        REVIEW_URL, json=review_json(allowed_png_b64=base64.b64encode(larger).decode())
    )
    assert rejected.status_code == 422 and not service.register_calls
    accepted = await http.post(
        REVIEW_URL, json=review_json(allowed_png_b64=base64.b64encode(exact).decode())
    )
    assert accepted.status_code == 200
    assert service.last_review.allowed_png == exact
    # This only checks the HTTP byte budget. A real processor still validates PNG/masks.


async def test_register_returns_provenance_and_condition_asset_urls(client):
    http, service = client
    await create(http)
    response = await http.post(REVIEW_URL, json=review_json())
    data = response.json()
    assert response.status_code == 200 and data["kind"] == "sam_registered_uv"
    assert data["mesh_url"] == BASE + "/conditions/45/mesh.glb"
    assert data["texture_url"] == BASE + "/conditions/45/texture.png"
    assert data["provenance"] == {"target_condition": 45, "research_only": True}
    raw = base64.b64decode(data["provenance_json_b64"], validate=True)
    assert json.loads(raw) == data["provenance"]
    assert base64.b64encode(raw).decode("ascii") == data["provenance_json_b64"]
    assert data["source_age"]["value"] == 42.5 and data["shape"] == [0.0] * 40
    assert service.registered and data["quality_accepted"] is False


async def test_exact_fractional_source_reset_returns_original_urls(client):
    http, _ = client
    await create(http)
    response = await http.post(BASE + "/absolute", json={"age": 42.5})
    assert response.status_code == 200 and response.json()["kind"] == "source_reset"
    assert response.json()["mesh_url"] == BASE + "/source.glb"
    fractional = await http.post(BASE + "/absolute", json={"age": 42.6})
    assert fractional.status_code == 422 and fractional.json()["code"] == "INTEGER_AGE_REQUIRED"


@pytest.mark.parametrize("age", [True, "45", 19, 71, None])
async def test_absolute_input_rejects_boolean_coercion_and_invalid_age(client, age):
    http, _ = client
    await create(http)
    response = await http.post(BASE + "/absolute", json={"age": age})
    assert response.status_code == 422


async def test_unknown_absolute_age_remains_rejected(client):
    http, _ = client
    await create(http, None)
    response = await http.post(BASE + "/absolute", json={"age": 45})
    assert response.status_code == 422 and response.json()["code"] == "SOURCE_AGE_REQUIRED"
    assert "private" not in response.text


@pytest.mark.parametrize(
    "path", ["/openapi.json", "/docs", "/redoc", "/api/health", "/api/aging", "/research/not-real"]
)
async def test_production_docs_and_unknown_routes_are_not_exposed(client, path):
    http, _ = client
    response = await http.get(path)
    assert response.status_code == 404 and response.json()["code"] == "BAD_INPUT"
    assert response.headers["cache-control"] == "no-store"


async def test_unexpected_error_body_does_not_echo_private_exception(client):
    http, _ = client
    await create(http)
    response = await http.post(BASE + "/absolute", json={"age": 46})
    assert response.status_code == 500 and response.json()["code"] == "INTERNAL_ERROR"
    assert "PRIVATE_PHOTO" not in response.text and "TOKEN" not in response.text
    assert response.headers["cache-control"] == "no-store"


async def test_asset_responses_release_leases_after_success(client):
    http, service = client
    await create(http)
    for path in (
        BASE + "/source.glb",
        BASE + "/source-texture.png",
        BASE + "/stages/" + STAGED.stage_id + "/preview.png",
        BASE + "/stages/" + STAGED.stage_id + "/fit.json",
    ):
        response = await http.get(path)
        assert response.status_code == 200 and service.downloads == 0
        assert response.headers["cache-control"] == "no-store"
    assert service.releases == 4


async def asgi_request(app, path, body=b"", *, chunks=None, disconnect=None, cancel_send=False):
    chunks = list(chunks) if chunks is not None else [body]
    sent, cursor, blocked = [], 0, asyncio.Event()

    async def receive():
        nonlocal cursor
        if cursor < len(chunks):
            chunk = chunks[cursor]
            cursor += 1
            return {"type": "http.request", "body": chunk, "more_body": cursor < len(chunks)}
        if disconnect is not None:
            await disconnect.wait()
            return {"type": "http.disconnect"}
        await blocked.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)
        if cancel_send and message["type"] == "http.response.body":
            raise asyncio.CancelledError

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET" if cancel_send else "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 80),
        "headers": [(b"host", b"127.0.0.1"), (b"content-type", b"image/png")],
    }
    await app(scope, receive, send)
    return sent


async def test_actual_chunked_body_limit_does_not_trust_missing_content_length():
    service = SyntheticService()
    app = create_research_app(service, Settings(max_json_bytes=32))
    async with app.router.lifespan_context(app):
        sent = await asgi_request(app, "/research/sessions", chunks=[b"x" * 20, b"y" * 20])
        assert sent[0]["status"] == 413
        assert json.loads(sent[1]["body"])["code"] == "PAYLOAD_TOO_LARGE"
        assert not service.created


async def test_disconnect_cancels_only_http_waiter_and_native_job_survives():
    service = SyntheticService(block_create=True)
    app = create_research_app(service)
    async with app.router.lifespan_context(app):
        sent = await asgi_request(
            app, "/research/sessions", b"synthetic photo", disconnect=service.entered
        )
        assert sent[0]["status"] == 499
        await asyncio.wait_for(service.waiter_cancelled.wait(), 1)
        assert service.native is not None and not service.native.done() and not service.created
        service.release.set()
        assert await service.native == SID
        assert not service.created


async def test_http_timeout_returns_before_controlled_native_job_finishes():
    service = SyntheticService(block_create=True)
    app = create_research_app(service, Settings(http_timeout_seconds=0.03))
    async with app.router.lifespan_context(app):
        sent = await asyncio.wait_for(
            asgi_request(app, "/research/sessions", b"synthetic photo"), 1
        )
        assert sent[0]["status"] == 504
        await asyncio.wait_for(service.waiter_cancelled.wait(), 1)
        assert service.native is not None and not service.native.done() and not service.created
        service.release.set()
        assert await service.native == SID


async def test_cancelled_asgi_send_releases_the_download_lease():
    service = SyntheticService()
    service.created = True
    app = create_research_app(service)
    async with app.router.lifespan_context(app):
        with pytest.raises(asyncio.CancelledError):
            await asgi_request(app, BASE + "/source.glb", cancel_send=True)
        assert service.downloads == 0 and service.releases == 1


@pytest.mark.parametrize("operation", ["create", "register"])
async def test_real_service_does_not_publish_after_asgi_already_observed_disconnect(operation):
    """Force receive-before-publication ordering with real charged service storage.

    Completing the owned native task wakes both the service's shield/wait_for
    callback chain and a disconnect receiver. The ASGI receiver can finish before
    the public service waiter resumes, while _connected has not resumed to cancel
    that waiter yet. A transport fake that only observes cancelled tasks misses it.
    """
    from agemorph3d.aging_sessions import AgingSessionCache
    from agemorph3d.research_aging_service import ResearchAgingService
    from test_research_aging_service import SyntheticBuilder, SyntheticProcessor

    events = []

    class ObservedCache(AgingSessionCache):
        def publish(self, source):
            events.append("publish")
            return super().publish(source)

        def remember(self, lease, age, result):
            events.append("remember")
            return super().remember(lease, age, result)

    builder = SyntheticBuilder(blocked=operation == "create")
    processor = SyntheticProcessor()
    cache = ObservedCache()
    service = ResearchAgingService(processor, builder, cache=cache)
    app = create_research_app(service)
    disconnect_gate = asyncio.Event()
    if operation == "create":
        path, content_type, body = "/research/sessions", b"image/png", b"synthetic transport image"
        entered, release = builder.entered, builder.release
    else:
        sid = await service.create(
            b"synthetic image", "image/png", SourceAge.model_validate(UNKNOWN)
        )
        staged = await service.stage(sid, 45)
        processor.block("register")
        entered, release = processor.entered, processor.release
        path = f"/research/sessions/{sid}/stages/{staged.stage_id}/reviews"
        content_type = b"application/json"
        body = json.dumps(
            review_json(
                source_fingerprint=staged.source_fingerprint,
                generated_sha256=staged.generated_sha256,
                fit_sha256=staged.fit_sha256,
            )
        ).encode()
    events.clear()
    received, sent = False, []

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnect_gate.wait()
        events.append("disconnect_observed")
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 80),
        "headers": [(b"host", b"127.0.0.1"), (b"content-type", content_type)],
    }
    async with app.router.lifespan_context(app):
        request = asyncio.create_task(app(scope, receive, send))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            # Only scheduling is controlled. Source/cache publication still runs
            # through the actual service, not a fake or monkeypatched method.
            native = service._active
            assert native is not None and not native.done()
            native.add_done_callback(lambda _done: disconnect_gate.set())
            release.set()
            await asyncio.wait_for(request, 2)
            assert "disconnect_observed" in events
            assert sent[0]["status"] == 499, sent
            publication = "publish" if operation == "create" else "remember"
            assert publication not in events, f"Observed ASGI ordering: {events}"
            assert cache.stats["entries"] == (0 if operation == "create" else 1)
            assert cache.stats["results"] == 0 and cache.stats["pins"] == 0
        finally:
            release.set()
            disconnect_gate.set()
            await asyncio.gather(request, return_exceptions=True)


async def test_register_result_conflict_is_safe_and_does_not_offer_review_urls(client, monkeypatch):
    http, service = client
    await create(http)

    async def conflicting(*_args, **_kwargs):
        raise ApiError(409, "RESULT_CONFLICT", "PRIVATE_RESULT_DIGEST_AND_SOURCE_PATH")

    monkeypatch.setattr(service, "register", conflicting)
    response = await http.post(REVIEW_URL, json=review_json())
    assert response.status_code == 409
    assert response.json() == {
        "code": "RESULT_CONFLICT",
        "detail": "相同条件已有不同注册结果，请新建研究会话。",
    }
    assert not service.registered and "PRIVATE_RESULT" not in response.text


@pytest.mark.parametrize("age", [None, "42.5"])
async def test_reconnect_reads_the_same_explicit_session_metadata_without_rebuilding(client, age):
    http, service = client
    created = await create(http, age)
    response = await http.get(BASE)
    assert response.status_code == 200 and response.json() == created
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["source_age"]["method"] == ("unknown" if age is None else "user")
    assert service.stage_calls == service.register_calls == []


async def test_reconnect_expired_session_has_no_private_metadata(client):
    http, _ = client
    response = await http.get(BASE)
    assert response.status_code == 404 and response.json()["code"] == "SESSION_EXPIRED"
    assert "private source detail" not in response.text

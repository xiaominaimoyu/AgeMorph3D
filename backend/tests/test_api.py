"""HTTP and WebSocket contracts for the production, model-free B1 service."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Event

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.websockets import WebSocketDisconnect

from agemorph3d.app import create_app
from agemorph3d.config import Settings

ORIGIN = "http://127.0.0.1:5173"
BASE_URL = "http://127.0.0.1"
WS_URL = "ws://127.0.0.1/ws/frame"


def picture(format: str = "PNG", size: tuple[int, int] = (16, 12)) -> bytes:
    output = BytesIO()
    with Image.new("RGB", size, "blue") as image:
        image.save(output, format=format)
    return output.getvalue()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AGEMORPH_ALLOWED_ORIGINS", raising=False)
    with TestClient(create_app(), base_url=BASE_URL) as connected:
        yield connected


def error(response, status: int, code: str | None = None) -> dict:
    assert response.status_code == status, response.text
    payload = response.json()
    assert isinstance(payload["detail"], str) and payload["detail"]
    if code is not None:
        assert payload["code"] == code
    return payload


def test_default_health_reports_four_missing_models(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["api_version"] == "1.2"
    assert payload["device"] == "cpu"
    assert payload["version"]
    assert set(payload["models"]) == {"detector", "reconstructor", "age_shape", "age_texture"}
    for model in payload["models"].values():
        assert model["state"] == "missing"
        assert model["backend"] is None
        assert model["provider"] is None
        assert isinstance(model["detail"], str) and model["detail"]
    assert payload["capabilities"] == {
        "reconstruction": False,
        "age_morph": False,
        "age_texture": False,
        "realtime": False,
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "format,mime",
    [
        ("PNG", "image/png"),
        ("JPEG", "image/jpeg"),
        ("WEBP", "image/webp"),
    ],
)
def test_real_multipart_reaches_missing_model(
    client: TestClient,
    format: str,
    mime: str,
) -> None:
    response = client.post(
        "/api/reconstruct",
        files={"image": ("subject", picture(format), mime)},
    )
    error(response, 503, "MODEL_NOT_READY")
    assert "mesh_id" not in response.json()


@pytest.mark.parametrize(
    "data,mime,status,code",
    [
        (b"", "image/png", 400, "BAD_INPUT"),
        (b"private-original-photo-invalid", "image/jpeg", 400, "BAD_INPUT"),
        (picture()[:40], "image/png", 400, "BAD_INPUT"),
        (picture(), "image/jpeg", 415, "UNSUPPORTED_MEDIA_TYPE"),
        (picture(), "application/octet-stream", 415, "UNSUPPORTED_MEDIA_TYPE"),
        (picture("GIF"), "image/png", 415, "UNSUPPORTED_MEDIA_TYPE"),
    ],
)
def test_multipart_checks_actual_image_and_media_type(
    client: TestClient,
    data: bytes,
    mime: str,
    status: int,
    code: str,
) -> None:
    response = client.post("/api/reconstruct", files={"image": ("private-name", data, mime)})
    error(response, status, code)
    assert "private-original-photo-invalid" not in response.text
    assert "private-name" not in response.text


@pytest.mark.parametrize(
    "files,status",
    [
        ([("other", ("a.png", picture(), "image/png"))], 422),
        ([("image", (None, "text field"))], 400),
        (
            [
                ("image", ("a.png", picture(), "image/png")),
                ("image", ("b.png", picture(), "image/png")),
            ],
            400,
        ),
        (
            [
                ("image", ("a.png", picture(), "image/png")),
                ("extra", (None, "private-value")),
            ],
            400,
        ),
    ],
)
def test_multipart_accepts_exactly_one_image_file(
    client: TestClient,
    files: list,
    status: int,
) -> None:
    error(client.post("/api/reconstruct", files=files), status, "BAD_INPUT")


def test_reconstruct_rejects_other_content_types_and_missing_boundary(client: TestClient) -> None:
    error(client.post("/api/reconstruct", json={"image": "private"}), 415, "BAD_INPUT")
    error(
        client.post(
            "/api/reconstruct",
            content=b"broken multipart",
            headers={"content-type": "multipart/form-data"},
        ),
        400,
        "BAD_INPUT",
    )


def test_image_file_byte_and_pixel_limits_apply_after_multipart() -> None:
    data = picture("JPEG")
    settings = Settings(max_image_bytes=len(data) - 1)
    with TestClient(create_app(settings), base_url=BASE_URL) as client:
        error(
            client.post(
                "/api/reconstruct",
                files={"image": ("a.jpg", data, "image/jpeg")},
            ),
            413,
            "INPUT_TOO_LARGE",
        )
    settings = Settings(max_image_bytes=len(data), max_image_pixels=16 * 12 - 1)
    with TestClient(create_app(settings), base_url=BASE_URL) as client:
        error(
            client.post(
                "/api/reconstruct",
                files={"image": ("a.jpg", data, "image/jpeg")},
            ),
            413,
            "INPUT_TOO_LARGE",
        )
    settings = Settings(max_image_bytes=len(data), max_image_pixels=16 * 12)
    with TestClient(create_app(settings), base_url=BASE_URL) as client:
        error(
            client.post(
                "/api/reconstruct",
                files={"image": ("a.jpg", data, "image/jpeg")},
            ),
            503,
            "MODEL_NOT_READY",
        )


@pytest.mark.parametrize(
    "path,limit",
    [
        ("/api/reconstruct", 64 * 1024 + 8),
        ("/api/aging", 128),
    ],
)
def test_content_length_and_actual_stream_bytes_are_both_bounded(path: str, limit: int) -> None:
    settings = Settings(max_image_bytes=8, max_json_bytes=128)
    with TestClient(create_app(settings), base_url=BASE_URL) as client:
        error(
            client.post(path, content=b"x", headers={"content-length": str(limit + 1)}),
            413,
            "PAYLOAD_TOO_LARGE",
        )

        def chunks():
            yield b"x" * limit
            yield b"x"

        streamed = client.post(path, content=chunks())
        assert "content-length" not in streamed.request.headers
        assert streamed.request.headers["transfer-encoding"] == "chunked"
        error(streamed, 413, "PAYLOAD_TOO_LARGE")
        error(
            client.post(
                path,
                content=b"x" * (limit + 1),
                headers={"content-length": "1"},
            ),
            413,
            "PAYLOAD_TOO_LARGE",
        )


@pytest.mark.parametrize(
    "headers",
    [
        {"content-length": "-1"},
        {"content-length": "invalid"},
        [("content-length", "1"), ("content-length", "2")],
    ],
)
def test_invalid_content_length_is_public_error(client: TestClient, headers) -> None:
    error(client.post("/api/aging", content=b"{}", headers=headers), 400, "BAD_INPUT")


@pytest.mark.parametrize(
    "length,status,code",
    [
        ("invalid", 400, "BAD_INPUT"),
        (str(128 * 1024 + 1), 413, "PAYLOAD_TOO_LARGE"),
    ],
)
@pytest.mark.parametrize("origin", [ORIGIN, "https://evil.example"])
def test_early_http_rejections_preserve_safe_cors_and_cache_headers(
    client: TestClient,
    length: str,
    status: int,
    code: str,
    origin: str,
) -> None:
    response = client.post(
        "/api/aging",
        content=b"{}",
        headers={"origin": origin, "content-length": length},
    )
    if origin == ORIGIN:
        error(response, status, code)
        assert response.headers.get("access-control-allow-origin") == ORIGIN
    else:
        error(response, 403, "ORIGIN_DENIED")
        assert "access-control-allow-origin" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert "access-control-allow-credentials" not in response.headers


async def asgi_post(app, receive, path: str = "/api/aging", content_type: str = "application/json"):
    messages = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"127.0.0.1"),
            (b"origin", ORIGIN.encode()),
            (b"content-type", content_type.encode()),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8000),
        "state": {},
    }

    async def send(message):
        messages.append(message)

    async with app.router.lifespan_context(app):
        try:
            await asyncio.wait_for(app(scope, receive, send), timeout=1)
        except TimeoutError:
            pytest.fail("HTTP reception failed to enforce the configured total deadline.")
    start = next(message for message in messages if message["type"] == "http.response.start")
    headers = {key.decode(): value.decode() for key, value in start["headers"]}
    body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return start["status"], headers, json.loads(body)


async def test_incomplete_body_has_a_total_receive_deadline() -> None:
    first = True

    async def receive():
        nonlocal first
        if first:
            first = False
            return {"type": "http.request", "body": b"{", "more_body": True}
        await asyncio.Future()

    status, headers, body = await asgi_post(
        create_app(Settings(http_timeout_seconds=0.01)),
        receive,
    )
    assert status == 504
    assert body["code"] == "TIMEOUT"
    assert isinstance(body["detail"], str)
    assert headers.get("access-control-allow-origin") == ORIGIN
    assert headers["cache-control"] == "no-store"
    assert "access-control-allow-credentials" not in headers


async def test_receive_and_image_decode_share_one_http_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agemorph3d.images import decode_image

    def slow_decode(*args, **kwargs):
        Event().wait(0.13)
        return decode_image(*args, **kwargs)

    monkeypatch.setattr("agemorph3d.runtime.decode_image", slow_decode)
    body = (
        b'--test-boundary\r\nContent-Disposition: form-data; name="image"; filename="a.png"'
        b"\r\nContent-Type: image/png\r\n\r\n" + picture() + b"\r\n--test-boundary--\r\n"
    )
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            # This client stays connected while the worker uses its remaining budget.
            await asyncio.Future()
        delivered = True
        await asyncio.sleep(0.13)
        return {"type": "http.request", "body": body, "more_body": False}

    status, headers, response = await asgi_post(
        create_app(Settings(http_timeout_seconds=0.2)),
        receive,
        path="/api/reconstruct",
        content_type="multipart/form-data; boundary=test-boundary",
    )
    assert status == 504
    assert response["code"] == "TIMEOUT"
    assert isinstance(response["detail"], str)
    assert headers.get("access-control-allow-origin") == ORIGIN
    assert headers["cache-control"] == "no-store"
    assert "access-control-allow-credentials" not in headers


def test_openapi_errors_share_a_string_detail_schema(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    definitions = document["components"]["schemas"]
    schema = definitions["ErrorResponse"]
    assert schema["properties"]["detail"]["type"] == "string"
    assert schema["properties"]["code"]["type"] == "string"
    assert set(schema["required"]) == {"detail", "code"}
    expected = {"$ref": "#/components/schemas/ErrorResponse"}
    routes = {
        ("/api/health", "get"): {"403", "500", "504"},
        ("/api/reconstruct", "post"): {
            "400",
            "403",
            "413",
            "415",
            "422",
            "429",
            "500",
            "503",
            "504",
        },
        ("/api/aging", "post"): {"400", "403", "413", "422", "500", "503", "504"},
        ("/api/assets/{mesh_id}/mesh.glb", "get"): {"403", "404", "500", "504"},
    }
    for (path, method), expected_statuses in routes.items():
        responses = document["paths"][path][method]["responses"]
        assert expected_statuses.issubset(responses), (path, responses)
        for status, entry in responses.items():
            if status.isdigit() and int(status) >= 400:
                assert entry["content"]["application/json"]["schema"] == expected, (path, status)


@pytest.mark.parametrize("age", [20, 45.5, 70])
def test_valid_aging_requests_report_unready(client: TestClient, age: float) -> None:
    error(
        client.post("/api/aging", json={"mesh_id": "subject-1_a", "age": age}),
        503,
        "MODEL_NOT_READY",
    )


@pytest.mark.parametrize(
    "payload",
    [{"mesh_id": "subject", "age": age} for age in [True, False, "45", None, 19.9, 70.1]]
    + [
        {"mesh_id": mesh_id, "age": 45}
        for mesh_id in ["", "../secret", "a/b", "_private", "a" * 101, "中文", 123]
    ]
    + [
        {"mesh_id": "subject", "age": 45, "private-extra": "sensitive-value"},
        {"age": 45},
        {"mesh_id": "subject"},
        {},
    ],
)
def test_aging_validation_is_strict_and_errors_are_strings(
    client: TestClient,
    payload: dict,
) -> None:
    response = client.post("/api/aging", json=payload)
    error(response, 422, "BAD_INPUT")
    assert "sensitive-value" not in response.text


@pytest.mark.parametrize("age", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_age_is_rejected(client: TestClient, age: str) -> None:
    error(
        client.post(
            "/api/aging",
            content='{"mesh_id":"subject","age":' + age + "}",
            headers={"content-type": "application/json"},
        ),
        422,
        "BAD_INPUT",
    )


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "https://evil.example"},
        {"origin": "null"},
        {"origin": "http://127.0.0.1:5173.evil.example"},
        {"host": "evil.example"},
        {"host": "127.0.0.1.evil.example"},
        {"host": "user@localhost"},
        {"host": "localhost:0"},
        [("origin", ORIGIN), ("origin", ORIGIN)],
        [("host", "127.0.0.1"), ("host", "evil.example")],
    ],
)
def test_http_host_and_origin_are_checked(client: TestClient, headers) -> None:
    error(client.get("/api/health", headers=headers), 403, "ORIGIN_DENIED")


def test_cors_allows_configured_origin_without_credentials(client: TestClient) -> None:
    response = client.get("/api/health", headers={"origin": ORIGIN})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-credentials" not in response.headers
    response = client.options(
        "/api/reconstruct",
        headers={
            "origin": ORIGIN,
            "access-control-request-method": "POST",
            "access-control-request-headers": "Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": ORIGIN, "host": "evil.example"},
        {"origin": "https://evil.example"},
    ],
)
def test_cors_preflight_cannot_bypass_local_access_checks(
    client: TestClient,
    headers: dict,
) -> None:
    response = client.options(
        "/api/reconstruct",
        headers={
            **headers,
            "access-control-request-method": "POST",
        },
    )
    error(response, 403, "ORIGIN_DENIED")
    assert "access-control-allow-origin" not in response.headers


def websocket_error(client: TestClient, data: bytes | str, code: str, close_code: int) -> None:
    with client.websocket_connect(WS_URL, headers={"origin": ORIGIN}) as websocket:
        assert websocket.receive_json() == {"type": "status", "device": "cpu"}
        if isinstance(data, str):
            websocket.send_text(data)
        else:
            websocket.send_bytes(data)
        text = websocket.receive_text()
        assert len(text.encode("utf-8")) <= 1024
        payload = json.loads(text)
        assert payload["type"] == "error"
        assert payload["seq"] == 1
        assert payload["code"] == code
        assert isinstance(payload["msg"], str) and payload["msg"]
        terminal = websocket.receive()
        assert terminal["type"] == "websocket.close"
        assert terminal["code"] == close_code


@pytest.mark.parametrize("size", [(16, 12), (640, 360), (1, 640)])
def test_valid_jpeg_frame_gets_one_unready_error_and_closes(
    client: TestClient,
    size: tuple[int, int],
) -> None:
    websocket_error(client, picture("JPEG", size), "MODEL_NOT_READY", 1013)


@pytest.mark.parametrize(
    "data,code",
    [
        ("do not accept text frames", "BAD_INPUT"),
        (b"", "BAD_INPUT"),
        (b"broken jpeg", "BAD_INPUT"),
        (picture("PNG"), "UNSUPPORTED_MEDIA_TYPE"),
        (picture("JPEG", (641, 1)), "INPUT_TOO_LARGE"),
        (picture("JPEG", (1, 641)), "INPUT_TOO_LARGE"),
        (b"x" * (2 * 1024**2 + 1), "INPUT_TOO_LARGE"),
    ],
    ids=["text", "empty", "broken", "png", "too-wide", "too-tall", "too-many-bytes"],
)
def test_bad_frames_get_one_bounded_error_and_close(
    client: TestClient,
    data: bytes | str,
    code: str,
) -> None:
    websocket_error(client, data, code, 1003)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"origin": "https://evil.example"},
        {"origin": "null"},
        {"origin": ORIGIN, "host": "evil.example"},
    ],
)
def test_websocket_rejects_missing_origin_remote_origin_and_host(
    client: TestClient,
    headers: dict,
) -> None:
    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect(WS_URL, headers=headers):
            pytest.fail("An untrusted WebSocket handshake must not be accepted.")
    assert caught.value.code == 1008


def test_assets_do_not_expose_arbitrary_disk_files(client: TestClient, tmp_path) -> None:
    marker = "private-disk-model-content"
    (tmp_path / "private.glb").write_text(marker)
    for path in [
        "/api/assets/subject/mesh.glb",
        "/api/assets/subject/texture.png",
        "/api/assets/..%2Fprivate.glb",
        "/assets/private.glb",
        "/" + (tmp_path / "private.glb").as_posix(),
    ]:
        response = client.get(path)
        error(response, 404)
        assert marker not in response.text


def test_unexpected_http_failure_has_private_safe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed_decode(*args, **kwargs):
        raise RuntimeError("private-original-photo-and-local-path")

    monkeypatch.setattr("agemorph3d.runtime.decode_image", failed_decode)
    with TestClient(create_app(), base_url=BASE_URL, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/reconstruct",
            files={"image": ("a.png", picture(), "image/png")},
            headers={"origin": ORIGIN},
        )
    error(response, 500, "INTERNAL_ERROR")
    assert "private-original-photo-and-local-path" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers.get("access-control-allow-origin") == ORIGIN
    assert "access-control-allow-credentials" not in response.headers


def test_unexpected_websocket_failure_has_one_private_safe_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_decode(*args, **kwargs):
        raise RuntimeError("private-original-photo-and-local-path")

    monkeypatch.setattr("agemorph3d.runtime.decode_image", failed_decode)
    with client.websocket_connect(WS_URL, headers={"origin": ORIGIN}) as websocket:
        assert websocket.receive_json() == {"type": "status", "device": "cpu"}
        websocket.send_bytes(picture("JPEG"))
        text = websocket.receive_text()
        assert len(text.encode("utf-8")) <= 1024
        assert "private-original-photo-and-local-path" not in text
        payload = json.loads(text)
        assert payload["type"] == "error"
        assert payload["code"] == "INTERNAL_ERROR"
        assert isinstance(payload["msg"], str) and payload["msg"]
        terminal = websocket.receive()
        assert terminal["type"] == "websocket.close"
        assert terminal["code"] == 1011


def test_health_remains_responsive_during_cpu_work(monkeypatch: pytest.MonkeyPatch) -> None:
    started, release = Event(), Event()
    from agemorph3d.images import decode_image

    def blocked_decode(*args, **kwargs):
        started.set()
        if not release.wait(5):
            raise AssertionError("The test did not release its blocked worker.")
        return decode_image(*args, **kwargs)

    monkeypatch.setattr("agemorph3d.runtime.decode_image", blocked_decode)
    with TestClient(create_app(), base_url=BASE_URL) as client:
        with ThreadPoolExecutor(max_workers=2) as requests:
            reconstruction = requests.submit(
                client.post,
                "/api/reconstruct",
                files={"image": ("a.png", picture(), "image/png")},
            )
            try:
                assert started.wait(1)
                health = requests.submit(client.get, "/api/health").result(timeout=1)
                assert health.status_code == 200
                assert not release.is_set()
                busy = client.post(
                    "/api/reconstruct",
                    files={"image": ("b.png", picture(), "image/png")},
                )
                error(busy, 429, "BUSY")
                assert busy.headers["retry-after"] == "1"
            finally:
                release.set()
            error(reconstruction.result(timeout=1), 503, "MODEL_NOT_READY")

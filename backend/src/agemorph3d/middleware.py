"""ASGI input limits and local-origin checks, before multipart/JSON parsing."""

import asyncio
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings


def private_error_headers(scope: Scope, settings: Settings) -> dict[str, str]:
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    origins = [v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"origin"]
    hosts = [v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"host"]
    if (
        len(origins) == 1
        and origins[0] in settings.allowed_origins
        and len(hosts) == 1
        and loopback_host(hosts[0])
    ):
        headers["Access-Control-Allow-Origin"] = origins[0]
        headers["Vary"] = "Origin"
    return headers


def loopback_host(value: str) -> bool:
    try:
        address = urlsplit(f"//{value}")
        return (
            address.hostname in {"localhost", "127.0.0.1", "::1"}
            and address.username is None
            and address.password is None
            and not address.path
            and not address.query
            and not address.fragment
            and (address.port is None or 0 < address.port <= 65535)
        )
    except ValueError:
        return False


class LocalRequestMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = scope.get("headers", [])
        hosts = [v.decode("latin-1") for k, v in headers if k == b"host"]
        origins = [v.decode("latin-1") for k, v in headers if k == b"origin"]
        is_ws = scope["type"] == "websocket"
        host_ok = len(hosts) == 1 and loopback_host(hosts[0])
        origin_ok = (len(origins) == 1 and origins[0] in self.settings.allowed_origins) or (
            not origins and not is_ws
        )
        if not host_ok or not origin_ok:
            if is_ws:
                await send({"type": "websocket.close", "code": 1008})
            else:
                await JSONResponse(
                    {"detail": "仅允许配置的本机页面访问此服务。", "code": "ORIGIN_DENIED"},
                    status_code=403,
                    headers=private_error_headers(scope, self.settings),
                )(scope, receive, send)
            return
        if is_ws:
            await self.app(scope, receive, send)
            return

        async def private_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key for key, _ in headers}
                for key, value in (
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ):
                    if key not in existing:
                        headers.append((key, value))
                message["headers"] = headers
            await send(message)

        limit = (
            self.settings.max_image_bytes + 64 * 1024
            if scope["path"] == "/api/reconstruct"
            else self.settings.max_json_bytes
        )
        lengths = [v for k, v in headers if k == b"content-length"]
        if lengths:
            try:
                if len(lengths) != 1 or int(lengths[0]) < 0:
                    raise ValueError
                if int(lengths[0]) > limit:
                    await self._reject(scope, receive, private_send, 413, "请求内容超过大小限制。")
                    return
            except ValueError:
                await self._reject(scope, receive, private_send, 400, "请求长度格式无效。")
                return

        # Count actual bytes too; Content-Length is optional and untrusted.
        body = bytearray()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.http_timeout_seconds
        scope.setdefault("state", {})["http_deadline"] = deadline
        while True:
            try:
                message = await asyncio.wait_for(receive(), timeout=max(0, deadline - loop.time()))
            except TimeoutError:
                await self._reject(
                    scope,
                    receive,
                    private_send,
                    504,
                    "请求内容接收超时，请重新提交。",
                )
                return
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                await self._reject(scope, receive, private_send, 413, "请求内容超过大小限制。")
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def buffered_receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, buffered_receive, private_send)

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status: int,
        detail: str,
    ) -> None:
        code = {413: "PAYLOAD_TOO_LARGE", 504: "TIMEOUT"}.get(status, "BAD_INPUT")
        await JSONResponse(
            {"detail": detail, "code": code},
            status_code=status,
            headers=private_error_headers(scope, self.settings),
        )(scope, receive, send)

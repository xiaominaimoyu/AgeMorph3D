"""Bounded private age contexts and an injectable, closed-by-default research pipeline.

This module has no production route, model loader or license override. The caller
owns preprocessing and its processor; a SAM image alone is not a registered atlas.
"""

from __future__ import annotations

import asyncio
import math
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .errors import ApiError
from .schemas import SourceAge


def _buffers(*values: bytes) -> int:
    if any(type(value) is not bytes or not value for value in values):
        raise ValueError("Context payloads must be nonempty immutable bytes.")
    return sum(map(len, values))


def _shape(values: tuple[float, ...]) -> None:
    if (
        type(values) is not tuple
        or not 1 <= len(values) <= 300
        or any(type(v) not in {int, float} or not math.isfinite(v) for v in values)
        or any(abs(v) > 1_000_000 for v in values)
    ):
        raise ValueError("Shape must be an immutable finite coefficient tuple.")


@dataclass(frozen=True)
class SessionSource:
    """Original encoded RGB, FFHQ PNG and fit/alignment context, never written to disk.

    Correspondence is the preprocessing owner's immutable serialization. Its format
    and model/UV hashes must be checked by that owner's processor before inference.
    Source age JSON preserves the existing validated provenance without mutable models.
    """

    source_age_json: bytes
    original_rgb: bytes
    aligned_png: bytes
    correspondence: bytes
    glb: bytes
    texture_png: bytes
    shape: tuple[float, ...]

    def __post_init__(self) -> None:
        _ = self.payload_bytes
        SourceAge.model_validate_json(self.source_age_json)
        _shape(self.shape)

    @property
    def source_age(self) -> SourceAge:
        return SourceAge.model_validate_json(self.source_age_json)

    @property
    def payload_bytes(self) -> int:
        return _buffers(
            self.source_age_json,
            self.original_rgb,
            self.aligned_png,
            self.correspondence,
            self.glb,
            self.texture_png,
        ) + 8 * len(self.shape)


@dataclass(frozen=True)
class SessionResult:
    glb: bytes
    texture_png: bytes
    shape: tuple[float, ...]
    kind: str

    def __post_init__(self) -> None:
        _ = self.payload_bytes
        _shape(self.shape)
        if self.kind not in {"source_reset", "sam_registered_uv", "synthetic_contract"}:
            raise ValueError("Result must explicitly identify its provenance.")

    @property
    def payload_bytes(self) -> int:
        return _buffers(self.glb, self.texture_png) + 8 * len(self.shape)


class SessionNotFound(Exception):
    pass


class SessionCapacityError(Exception):
    pass


class SessionClosed(Exception):
    pass


@dataclass
class _Entry:
    source: SessionSource
    expires: float
    pins: int = 0
    results: dict[float, SessionResult] = field(default_factory=dict)

    @property
    def payload_bytes(self) -> int:
        return self.source.payload_bytes + sum(r.payload_bytes for r in self.results.values())


class SessionLease:
    def __init__(self, owner: AgingSessionCache, session_id: str, entry: _Entry):
        self._owner = owner
        self._id = session_id
        self._entry = entry
        self._closed = False

    @property
    def source(self) -> SessionSource:
        if self._closed:
            raise SessionNotFound()
        return self._entry.source

    def close(self) -> None:
        with self._owner._lock:
            if not self._closed:
                self._closed = True
                self._entry.pins -= 1
                self._owner._purge()

    def __enter__(self) -> SessionLease:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class AgingSessionCache:
    """Fixed TTL/LRU; expired or closed in-flight payloads stay charged until release.

    The budget counts serialized bytes and float64 coefficient payloads, not Python
    object overhead. Consumers must call sweep periodically for prompt idle expiry.
    """

    def __init__(
        self,
        *,
        max_bytes: int = 128 * 1024**2,
        max_entries: int = 16,
        ttl_seconds: float = 300,
        clock: Callable[[], float] = time.monotonic,
    ):
        if any(type(v) is not int or v <= 0 for v in (max_bytes, max_entries)):
            raise ValueError("Cache bounds must be positive integers.")
        if (
            type(ttl_seconds) not in {int, float}
            or not math.isfinite(ttl_seconds)
            or ttl_seconds <= 0
        ):
            raise ValueError("TTL must be finite and positive.")
        self._max_bytes = max_bytes
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.RLock()
        self._closed = False

    def _purge(self) -> None:
        now = self._clock()
        for key, entry in list(self._entries.items()):
            if entry.pins == 0 and (self._closed or now >= entry.expires):
                del self._entries[key]

    def _room(self, extra_bytes: int, extra_entries: int) -> None:
        size = sum(entry.payload_bytes for entry in self._entries.values()) + extra_bytes
        count = len(self._entries) + extra_entries
        evict = []
        for key, entry in self._entries.items():
            if size <= self._max_bytes and count <= self._max_entries:
                break
            if entry.pins == 0:
                evict.append(key)
                size -= entry.payload_bytes
                count -= 1
        if size > self._max_bytes or count > self._max_entries:
            raise SessionCapacityError()
        for key in evict:
            del self._entries[key]

    def publish(self, source: SessionSource) -> str:
        if not isinstance(source, SessionSource):
            raise ValueError("Expected immutable source context.")
        with self._lock:
            if self._closed:
                raise SessionClosed()
            self._purge()
            self._room(source.payload_bytes, 1)
            session_id = secrets.token_hex(16)
            self._entries[session_id] = _Entry(source, self._clock() + self._ttl)
            return session_id

    def acquire(self, session_id: str) -> SessionLease:
        with self._lock:
            if self._closed:
                raise SessionClosed()
            self._purge()
            entry = self._entries.get(session_id)
            if entry is None or self._clock() >= entry.expires:
                raise SessionNotFound()
            entry.pins += 1
            self._entries.move_to_end(session_id)
            return SessionLease(self, session_id, entry)

    def _live(self, lease: SessionLease) -> _Entry:
        if self._closed:
            raise SessionClosed()
        if (
            lease._owner is not self
            or lease._closed
            or self._entries.get(lease._id) is not lease._entry
            or self._clock() >= lease._entry.expires
        ):
            raise SessionNotFound()
        return lease._entry

    def get_result(self, lease: SessionLease, age: float) -> SessionResult | None:
        self._age_key(age)
        with self._lock:
            return self._live(lease).results.get(age)

    def remember(self, lease: SessionLease, age: float, result: SessionResult) -> None:
        self._age_key(age)
        if not isinstance(result, SessionResult):
            raise ValueError("Expected validated immutable result.")
        with self._lock:
            entry = self._live(lease)
            if age in entry.results:
                return
            self._room(result.payload_bytes, 0)
            entry.results[age] = result

    @staticmethod
    def _age_key(age: float) -> None:
        if type(age) not in {int, float} or not math.isfinite(age) or not 20 <= age <= 70:
            raise ValueError("Cache age must be finite and within 20–70.")

    def sweep(self) -> None:
        with self._lock:
            self._purge()

    @property
    def stats(self) -> dict[str, int | bool]:
        with self._lock:
            self._purge()
            return {
                "entries": len(self._entries),
                "payload_bytes": sum(e.payload_bytes for e in self._entries.values()),
                "pins": sum(e.pins for e in self._entries.values()),
                "results": sum(len(e.results) for e in self._entries.values()),
                "closed": self._closed,
            }

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._purge()


Processor = Callable[[SessionSource, int], Awaitable[SessionResult]]


class AgingCoordinator:
    """Synthetic/offline orchestration; no production capability is granted here.

    A processor must not finish while its native work still owns resources. With
    SamWorkerClient, await wait_idle() in the processor's finally block even after
    an inner timeout. Its generated PNG still needs target reconstruction, a valid
    target occlusion policy and UV registration before becoming a SessionResult.
    At shutdown, close the owned bounded worker before/concurrently with this
    coordinator's drain, so a hung native request cannot make that drain unbounded.
    """

    def __init__(self, cache: AgingSessionCache, processor: Processor):
        self.cache = cache
        self._processor = processor
        self._active: asyncio.Task[SessionResult] | None = None
        self._closed = False
        self._shutdown: asyncio.Task[None] | None = None
        self._sweeper: asyncio.Task[None] | None = None

    async def start(self, sweep_interval_seconds: float = 1) -> None:
        """Own periodic expiry, independent of whether another request arrives."""
        if (
            type(sweep_interval_seconds) not in {int, float}
            or not math.isfinite(sweep_interval_seconds)
            or sweep_interval_seconds <= 0
        ):
            raise ValueError("Sweep interval must be finite and positive.")
        if self._closed:
            raise SessionClosed()
        if self._sweeper is None:

            async def sweep() -> None:
                while True:
                    await asyncio.sleep(sweep_interval_seconds)
                    self.cache.sweep()

            self._sweeper = asyncio.create_task(sweep())

    async def generate(
        self, session_id: str, age: float, timeout_seconds: float = 25
    ) -> SessionResult:
        if self._closed:
            raise ApiError(503, "MODEL_NOT_READY", "本地年龄会话正在关闭。")
        if type(age) not in {int, float} or not math.isfinite(age) or not 20 <= age <= 70:
            raise ApiError(422, "BAD_INPUT", "目标年龄必须为 20—70 的有限数值。")
        if (
            type(timeout_seconds) not in {int, float}
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("Timeout must be positive and finite.")
        lease = None
        task = None
        try:
            lease = self.cache.acquire(session_id)
            source = lease.source
            if source.source_age.value is None:
                raise ApiError(422, "SOURCE_AGE_REQUIRED", "绝对年龄需要已知源年龄。")
            if age == source.source_age.value:
                return SessionResult(source.glb, source.texture_png, source.shape, "source_reset")
            if not float(age).is_integer():
                raise ApiError(422, "INTEGER_AGE_REQUIRED", "SAM 直接生成仅支持整数年龄条件。")
            cached = self.cache.get_result(lease, age)
            if cached is not None:
                return cached
            if self._active is not None:
                raise ApiError(429, "BUSY", "年龄处理资源正忙，请稍后重试。")

            deadline = asyncio.get_running_loop().time() + timeout_seconds
            task = asyncio.create_task(self._processor(source, int(age)))
            self._active = task

            def finished(result: asyncio.Task[SessionResult]) -> None:
                if self._active is result:
                    self._active = None
                if not result.cancelled():
                    result.exception()

            task.add_done_callback(finished)
            try:
                result = await asyncio.wait_for(asyncio.shield(task), timeout_seconds)
            except TimeoutError:
                raise ApiError(504, "TIMEOUT", "年龄处理超时，请稍后重试。") from None
            if self._closed:
                raise ApiError(503, "MODEL_NOT_READY", "本地年龄会话正在关闭。")
            if asyncio.get_running_loop().time() >= deadline:
                raise ApiError(504, "TIMEOUT", "年龄处理超时，请稍后重试。")
            # No await here: expired/abandoned work never publishes a cached result.
            self.cache.remember(lease, age, result)
            return result
        except (SessionNotFound, SessionClosed):
            raise ApiError(404, "SESSION_EXPIRED", "年龄会话不存在或已过期，请重新重建。") from None
        except SessionCapacityError:
            raise ApiError(429, "BUSY", "年龄会话缓存已满，请稍后重试。") from None
        finally:
            if lease is not None:
                if task is not None and not task.done():
                    # The native processor still reads this source and owns admission.
                    task.add_done_callback(lambda _result, held=lease: held.close())
                else:
                    lease.close()

    async def close(self) -> None:
        if self._shutdown is None:
            self._closed = True
            self.cache.close()
            running = self._active

            async def drain() -> None:
                if self._sweeper is not None:
                    self._sweeper.cancel()
                    await asyncio.gather(self._sweeper, return_exceptions=True)
                if running is not None:
                    await asyncio.gather(running, return_exceptions=True)

            self._shutdown = asyncio.create_task(drain())
        await asyncio.shield(self._shutdown)

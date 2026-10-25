"""Owned, bounded research sessions around the isolated aging processor.

The caller owns detector/reconstructor models used by ``source_builder`` and
closes them after this service. This service owns its processor, source cache,
native admission, sweeper and response leases. No production readiness changes.
"""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock

from .aging_sessions import (
    AgingCoordinator,
    AgingSessionCache,
    SessionCapacityError,
    SessionClosed,
    SessionLease,
    SessionNotFound,
    SessionResult,
    SessionSource,
)
from .errors import ApiError
from .research_aging_pipeline import (
    RegisteredConditionResult,
    ReviewRequired,
    StagedPreview,
    StagedTarget,
    TargetMaskReview,
    _drain,
    source_fingerprint,
)
from .schemas import SourceAge

_FLAGS = {
    "research_only": True,
    "service_ready": False,
    "production_enabled": False,
    "g3_complete": False,
    "age_quality_accepted": False,
    "identity_quality_accepted": False,
    "visual_seam_quality_accepted": False,
    "years_calibrated": False,
    "human_review_completed": False,
}

# An HTTP owner may install a synchronous disconnect/deadline check before
# creating its operation task. Child native tasks inherit the same context.
PUBLICATION_GUARD: ContextVar[Callable[[], None] | None] = ContextVar(
    "agemorph3d_research_publication_guard", default=None
)


def _condition(value: object) -> int:
    if type(value) is not int or not 20 <= value <= 70:
        raise ApiError(422, "INTEGER_AGE_REQUIRED", "研究生成条件必须为20—70的整数。")
    return value


def _timeout(value: object) -> float:
    if type(value) not in {int, float} or not math.isfinite(value) or not 0 < value <= 180:
        raise ValueError("Research timeout must be finite and within(0,180]seconds.")
    return float(value)


@dataclass
class _Waiting:
    deadline: float
    abandoned: bool = False
    caller: asyncio.Task | None = None


class _CoordinatorCache:
    """Delegate to the one real cache and guard Coordinator's commit boundary.

    Python3.11 wait_for can return an already-complete result while its caller
    is cancelling. Checking only after Coordinator.generate would be too late:
    its remember call may already have cached an abandoned successful result.
    """

    def __init__(self, cache: AgingSessionCache, before_remember: Callable[[], None]):
        self._cache, self._before_remember = cache, before_remember

    def __getattr__(self, name):
        return getattr(self._cache, name)

    def remember(self, lease, age, result):
        self._before_remember()
        self._cache.remember(lease, age, result)


class ResearchAssetLease:
    """Keep a source cache entry and a bounded download slot until send finishes."""

    def __init__(self, data: bytes, source: SessionLease, release: Callable[[], None], stage=None):
        self._data: bytes | None = data
        self._source: SessionLease | None = source
        self._stage = stage
        self._release: Callable[[], None] | None = release
        self._lock = Lock()

    @property
    def data(self) -> bytes:
        with self._lock:
            if self._data is None:
                raise RuntimeError("Research asset lease is closed.")
            return self._data

    def close(self) -> None:
        with self._lock:
            source, stage, release = self._source, self._stage, self._release
            self._stage = None
            self._source = self._release = self._data = None
        try:
            try:
                if stage is not None:
                    stage.close()
            finally:
                if source is not None:
                    source.close()
        finally:
            if release is not None:
                release()

    def __enter__(self) -> ResearchAssetLease:
        _ = self.data
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class ResearchAgingService:
    """One native slot shared by source reconstruction and all target processing.

    Public timeouts/disconnect cancellation abandon waiting, not native work.
    Actual tasks keep their leases/admission and cannot publish late results.
    Session results remain in the existing charged cache; sidecars are returned
    directly and are not another persistent result cache.
    """

    def __init__(
        self,
        processor,
        source_builder: Callable[[bytes, str, SourceAge], SessionSource],
        *,
        cache: AgingSessionCache | None = None,
        max_stages: int = 4,
        max_downloads: int = 4,
    ):
        if not callable(processor) or not callable(source_builder):
            raise ValueError("An explicit processor and synchronous source builder are required.")
        for name in (
            "stage_condition",
            "preview_staged",
            "register_reviewed",
            "sweep_stages",
            "close",
        ):
            if not callable(getattr(processor, name, None)):
                raise ValueError("Processor does not implement the isolated research contract.")
        if any(type(n) is not int or not 1 <= n <= 4 for n in (max_stages, max_downloads)):
            raise ValueError("Research stage/download limits must be integers within1..4.")
        self.processor = processor
        self.cache = AgingSessionCache() if cache is None else cache
        if not isinstance(self.cache, AgingSessionCache):
            raise ValueError("Research sessions require the existing charged source cache.")
        # Read the existing internal limits without modifying its frozen module.
        if (
            self.cache._max_bytes > 128 * 1024**2
            or self.cache._max_entries > 16
            or self.cache._ttl > 300
        ):
            raise ValueError("Injected session cache exceeds the research budget.")
        self._builder = source_builder
        self._max_stages, self._max_downloads = max_stages, max_downloads
        self._stages: OrderedDict[tuple[str, str], StagedTarget] = OrderedDict()
        self._downloads = 0
        self._download_lock = Lock()
        self._active: asyncio.Task | None = None
        self._cpu: asyncio.Task | None = None
        self._closed = False
        self._sweeper: asyncio.Task | None = None
        self._shutdown: asyncio.Task | None = None
        # The shared slot is inside Coordinator's actual processor task. A
        # coordinator timeout therefore cannot free it while native work lives.
        self._absolute_context: ContextVar[_Waiting | None] = ContextVar(
            "agemorph3d_research_absolute_waiter", default=None
        )
        self.coordinator = AgingCoordinator(
            _CoordinatorCache(self.cache, self._before_absolute_remember), self._absolute_processor
        )

    def snapshot(self) -> dict:
        with self._download_lock:
            downloads = self._downloads
        return {
            "closed": self._closed,
            "active": self._active is not None and not self._active.done(),
            "native_cpu_active": self._cpu is not None and not self._cpu.done(),
            "stage_entries": len(self._stages),
            "downloads": downloads,
            "cache": self.cache.stats,
            "processor": self.processor.snapshot,
            **_FLAGS,
        }

    def _open(self) -> None:
        if self._closed:
            raise ApiError(503, "MODEL_NOT_READY", "本地研究会话正在关闭。")

    def _acquire(self, session_id: str) -> SessionLease:
        self._open()
        if not isinstance(session_id, str):
            raise ApiError(404, "SESSION_EXPIRED", "研究会话不存在或已过期。")
        try:
            return self.cache.acquire(session_id)
        except (SessionNotFound, SessionClosed):
            raise ApiError(404, "SESSION_EXPIRED", "研究会话不存在或已过期。") from None

    def _fresh(self, session_id: str) -> None:
        with self._acquire(session_id):
            pass

    def _pending(self, timeout_seconds: float) -> _Waiting:
        return _Waiting(
            asyncio.get_running_loop().time() + _timeout(timeout_seconds),
            caller=asyncio.current_task(),
        )

    def _publishable(self, waiting: _Waiting) -> None:
        self._open()
        guard = PUBLICATION_GUARD.get()
        if guard is not None:
            guard()
        if waiting.caller is not None and waiting.caller.cancelling():
            waiting.abandoned = True
            raise asyncio.CancelledError
        if waiting.abandoned or asyncio.get_running_loop().time() >= waiting.deadline:
            raise ApiError(504, "TIMEOUT", "研究处理已超时或请求已离开。")

    def _before_absolute_remember(self) -> None:
        waiting = self._absolute_context.get()
        if waiting is None:
            raise ApiError(503, "MODEL_NOT_READY", "研究绝对年龄请求缺少所有权上下文。")
        self._publishable(waiting)

    def _launch(self, function, *args) -> asyncio.Task:
        self._open()
        if self._active is not None and not self._active.done():
            raise ApiError(429, "BUSY", "研究处理资源正忙。")
        task = asyncio.create_task(function(*args))
        self._active = task

        def finished(done):
            if self._active is done:
                self._active = None
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        return task

    async def _wait(self, task: asyncio.Task, waiting: _Waiting):
        try:
            result = await asyncio.wait_for(
                asyncio.shield(task), max(0, waiting.deadline - asyncio.get_running_loop().time())
            )
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                waiting.abandoned = True
                raise asyncio.CancelledError
            self._publishable(waiting)
            return result
        except TimeoutError:
            waiting.abandoned = True
            raise ApiError(504, "TIMEOUT", "研究处理超时，请稍后重试。") from None
        except asyncio.CancelledError:
            waiting.abandoned = True
            raise

    async def create(
        self, image: bytes, content_type: str, source_age: SourceAge, timeout_seconds: float = 180
    ) -> str:
        if (
            type(image) is not bytes
            or not image
            or len(image) > 10 * 1024**2
            or not isinstance(content_type, str)
            or not 0 < len(content_type) <= 128
            or not isinstance(source_age, SourceAge)
        ):
            raise ApiError(422, "BAD_INPUT", "研究图片或源年龄字段无效。")
        waiting = self._pending(timeout_seconds)
        source = await self._wait(
            self._launch(self._build, image, content_type, source_age, waiting), waiting
        )
        # Publication belongs to the still-present waiter, with no await between
        # its final deadline check and the cache mutation.
        try:
            return self.cache.publish(source)
        except SessionCapacityError:
            raise ApiError(429, "BUSY", "研究会话缓存已满。") from None

    async def _build(self, image, content_type, source_age, waiting):
        task = asyncio.create_task(
            asyncio.to_thread(self._builder, image, content_type, source_age)
        )
        self._cpu = task
        try:
            try:
                source = await _drain(task)
            except ApiError:
                raise
            except Exception:
                raise ApiError(500, "RECONSTRUCTION_FAILED", "研究源图重建失败。") from None
            if not isinstance(source, SessionSource) or source.source_age != source_age:
                raise ApiError(500, "INVALID_CONTEXT", "研究源上下文与明确源年龄不匹配。")
            self._publishable(waiting)
            return source
        finally:
            if self._cpu is task:
                self._cpu = None

    def _remember_stage(self, session_id: str, target: StagedTarget) -> None:
        self._fresh(session_id)
        key = (session_id, target.stage_id)
        self._stages[key] = target
        self._stages.move_to_end(key)
        while len(self._stages) > self._max_stages:
            self._stages.popitem(last=False)

    def _target(self, session_id: str, stage_id: str) -> StagedTarget:
        key = (session_id, stage_id)
        target = self._stages.get(key) if isinstance(stage_id, str) else None
        if target is None:
            raise ApiError(404, "STAGE_EXPIRED", "审核目标不存在、已过期或不属于此会话。")
        self._stages.move_to_end(key)
        return target

    async def stage(
        self, session_id: str, condition: int, timeout_seconds: float = 180
    ) -> StagedTarget:
        _condition(condition)
        waiting = self._pending(timeout_seconds)
        lease = self._acquire(session_id)
        try:
            task = self._launch(self._stage, session_id, lease, condition, waiting)
        except BaseException:
            lease.close()
            raise
        target = await self._wait(task, waiting)
        self._remember_stage(session_id, target)
        return target

    async def _stage(self, session_id, lease, condition, waiting):
        try:
            target = await self.processor.stage_condition(lease.source, condition)
            self._publishable(waiting)
            self._fresh(session_id)
            return target
        finally:
            lease.close()

    def preview(self, session_id: str, stage_id: str) -> StagedPreview:
        with self._acquire(session_id):
            return self.processor.preview_staged(self._target(session_id, stage_id))

    async def register(
        self, session_id: str, stage_id: str, review: TargetMaskReview, timeout_seconds: float = 180
    ) -> RegisteredConditionResult:
        waiting = self._pending(timeout_seconds)
        lease = self._acquire(session_id)
        try:
            target = self._target(session_id, stage_id)
            task = self._launch(self._register, session_id, lease, target, review, waiting)
        except BaseException:
            lease.close()
            raise
        registered = await self._wait(task, waiting)
        with self._acquire(session_id) as current:
            try:
                existing = self.cache.get_result(current, target.target_condition)
                if existing is not None and existing != registered.result:
                    raise ApiError(409, "RESULT_CONFLICT", "此条件已有不同审核结果，请使用新会话。")
                self.cache.remember(current, target.target_condition, registered.result)
            except (SessionClosed, SessionNotFound):
                raise ApiError(404, "SESSION_EXPIRED", "研究会话不存在或已过期。") from None
            except SessionCapacityError:
                raise ApiError(429, "BUSY", "研究会话缓存已满。") from None
        return registered

    async def _register(self, session_id, lease, target, review, waiting):
        try:
            registered = await self.processor.register_reviewed(lease.source, target, review)
            self._publishable(waiting)
            self._fresh(session_id)
            return registered
        finally:
            lease.close()

    async def _absolute_processor(self, source, age):
        return await _drain(self._launch(self.processor, source, age))

    async def absolute(
        self, session_id: str, age: float, timeout_seconds: float = 180
    ) -> SessionResult:
        self._open()
        timeout_seconds = _timeout(timeout_seconds)
        waiting = self._pending(timeout_seconds)
        token = self._absolute_context.set(waiting)
        try:
            result = await self.coordinator.generate(session_id, age, timeout_seconds)
            self._publishable(waiting)
            return result
        except ReviewRequired as error:
            self._publishable(waiting)
            self._remember_stage(session_id, error.staged)
            raise
        except asyncio.CancelledError:
            waiting.abandoned = True
            raise
        finally:
            self._absolute_context.reset(token)

    def source_info(self, session_id: str) -> dict:
        with self._acquire(session_id) as lease:
            source = lease.source
            return {
                "session_id": session_id,
                "source_age": source.source_age.model_dump(),
                "source_fingerprint": source_fingerprint(source),
                "shape": list(source.shape),
                **_FLAGS,
            }

    def _release_download(self) -> None:
        with self._download_lock:
            self._downloads -= 1

    def asset(self, session_id: str, kind: str, condition=None) -> ResearchAssetLease:
        self._open()
        with self._download_lock:
            if self._downloads >= self._max_downloads:
                raise ApiError(429, "BUSY", "研究资产下载资源正忙。")
            self._downloads += 1
        lease = None
        stage_lease = None
        try:
            lease = self._acquire(session_id)
            limit = 64 * 1024**2
            if kind == "source_glb":
                data = lease.source.glb
            elif kind == "source_texture":
                data = lease.source.texture_png
            elif kind in {"glb", "texture"}:
                _condition(condition)
                result = self.cache.get_result(lease, condition)
                if result is None:
                    raise ApiError(404, "RESULT_NOT_FOUND", "研究条件尚无已注册结果。")
                data = result.glb if kind == "glb" else result.texture_png
            elif kind in {"preview", "fit"}:
                target = self._target(session_id, condition)
                # Real processor stage storage stays charged during send, not
                # only while decoding its preview. Duck test processors may
                # omit an actual store; no stage pin is claimed for those.
                acquire_stage = getattr(self.processor, "_lease", None)
                if callable(acquire_stage):
                    stage_lease = acquire_stage(target)
                preview = self.processor.preview_staged(target)
                data = preview.png if kind == "preview" else preview.fit_bytes
                limit = 16 * 1024**2
            else:
                raise ApiError(404, "RESULT_NOT_FOUND", "研究资产种类不存在。")
            if type(data) is not bytes or not 0 < len(data) <= limit:
                raise ApiError(500, "INVALID_CONTEXT", "研究资产超出有界字节预算。")
            return ResearchAssetLease(data, lease, self._release_download, stage_lease)
        except BaseException as error:
            try:
                if stage_lease is not None:
                    stage_lease.close()
            finally:
                if lease is not None:
                    lease.close()
                self._release_download()
            if isinstance(error, (SessionNotFound, SessionClosed)):
                raise ApiError(404, "SESSION_EXPIRED", "研究会话不存在或已过期。") from None
            raise

    def sweep(self) -> None:
        self.cache.sweep()
        self.processor.sweep_stages()
        for key, target in list(self._stages.items()):
            session_id, _stage_id = key
            try:
                with self._acquire(session_id):
                    self.processor.preview_staged(target)
            except ApiError:
                self._stages.pop(key, None)

    async def start(self, interval: float = 1) -> None:
        self._open()
        if type(interval) not in {int, float} or not math.isfinite(interval) or interval <= 0:
            raise ValueError("Sweep interval must be finite and positive.")
        if self._sweeper is None:

            async def sweeping():
                while True:
                    await asyncio.sleep(interval)
                    self.sweep()

            self._sweeper = asyncio.create_task(sweeping())

    async def close(self) -> dict:
        if self._shutdown is None:
            self._closed = True

            async def shutdown():
                if self._sweeper is not None:
                    self._sweeper.cancel()
                    await asyncio.gather(self._sweeper, return_exceptions=True)
                active = self._active
                jobs = [self.processor.close(), self.coordinator.close()]
                if active is not None:
                    jobs.append(asyncio.shield(active))
                try:
                    results = await asyncio.gather(*jobs, return_exceptions=True)
                    for result in results[:2]:
                        if isinstance(result, BaseException):
                            raise ApiError(503, "WORKER_FAILED", "研究会话资源关闭失败。")
                finally:
                    self.cache.close()
                    self._stages.clear()

            self._shutdown = asyncio.create_task(shutdown())
        await _drain(self._shutdown)
        return self.snapshot()

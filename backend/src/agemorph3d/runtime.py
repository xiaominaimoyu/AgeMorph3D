"""Lifespan-owned state and a bounded worker for CPU image validation."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from . import __version__
from .config import Settings
from .errors import ApiError
from .model_lifecycle import ModelLifecycle
from .schemas import Capabilities, Health

T = TypeVar("T")


class Runtime:
    def __init__(self, settings: Settings | None = None) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agemorph3d")
        self._active = False
        self._closed = False
        self._started = False
        self._initialization: asyncio.Future[None] | None = None
        self._shutdown: asyncio.Task[None] | None = None
        self._models = ModelLifecycle(settings or Settings())

    async def start(self) -> None:
        """Schedule initialization once without blocking API startup or health."""
        if self._started or self._closed:
            return
        if self._active:
            raise ApiError(429, "BUSY", "本地处理资源正忙，请稍后重试。")
        self._started = True
        if self._models.begin():
            self._initialization = self._submit(self._models.initialize)

    def health(self) -> Health:
        return Health(
            api_version="1.2",
            version=__version__,
            device="cpu",
            models=self._models.snapshot(),
            # Individual operators do not establish the unpublished HTTP/WS chain.
            capabilities=Capabilities(),
        )

    def _submit(self, work: Callable[[], T]) -> asyncio.Future[T]:
        self._active = True
        try:
            future = asyncio.wrap_future(self._executor.submit(work))
        except BaseException:
            self._active = False
            raise

        def finished(result: asyncio.Future[T]) -> None:
            self._active = False
            # Retrieve errors even if the HTTP/WS caller already cancelled or timed out.
            if not result.cancelled():
                result.exception()

        future.add_done_callback(finished)
        return future

    async def run(self, work: Callable[[], T], timeout: float) -> T:  # noqa: ASYNC109
        if self._closed:
            raise ApiError(503, "MODEL_NOT_READY", "本地服务正在关闭。")
        if self._active:
            raise ApiError(429, "BUSY", "本地处理资源正忙，请稍后重试。")
        future = self._submit(work)
        try:
            # A timeout must not free the slot while the worker is still running.
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except TimeoutError as exc:
            raise ApiError(504, "TIMEOUT", "本地处理超时，请稍后重试。") from exc

    async def close(self) -> None:
        if self._shutdown is None:
            self._closed = True
            self._models.stop()
            # A single cleanup job follows the actual running worker. No model
            # inference can be admitted after stop, and late models cannot publish.
            self._executor.submit(self._models.close)
            self._shutdown = asyncio.create_task(
                asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=False)
            )
        # Cancelling a shutdown waiter cannot cancel actual thread/resource cleanup.
        await asyncio.shield(self._shutdown)


def model_not_ready() -> ApiError:
    return ApiError(503, "MODEL_NOT_READY", "所需模型尚未就绪，请先完成模型与资产接入。")

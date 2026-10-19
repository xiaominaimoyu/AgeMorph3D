"""Lifespan-owned state and a bounded worker for CPU image validation."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from . import __version__
from .errors import ApiError
from .schemas import Capabilities, Health, ModelStatus

T = TypeVar("T")


class Runtime:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agemorph3d")
        self._active = False
        self._closed = False

    def health(self) -> Health:
        # File presence and device visibility do not establish inference readiness.
        return Health(
            api_version="1.1",
            version=__version__,
            device="cpu",
            models={
                name: ModelStatus(
                    state="missing",
                    backend=None,
                    provider=None,
                    detail=detail,
                )
                for name, detail in {
                    "detector": "尚未接入已核验的 YOLO 人脸检测模型。",
                    "reconstructor": "尚未接入已核验的三维重建模型及拓扑资产。",
                    "age_shape": "尚未接入可追溯且经过校准的年龄形状资产。",
                    "age_texture": "尚未接入年龄纹理模型及 UV 投影。",
                }.items()
            },
            capabilities=Capabilities(),
        )

    async def run(self, work: Callable[[], T], timeout: float) -> T:  # noqa: ASYNC109
        if self._closed:
            raise ApiError(503, "MODEL_NOT_READY", "本地服务正在关闭。")
        if self._active:
            raise ApiError(429, "BUSY", "本地处理资源正忙，请稍后重试。")
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
        try:
            # A timeout must not free the slot while the worker is still running.
            return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        except TimeoutError as exc:
            raise ApiError(504, "TIMEOUT", "本地处理超时，请稍后重试。") from exc

    async def close(self) -> None:
        self._closed = True
        await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=True)


def model_not_ready() -> ApiError:
    return ApiError(503, "MODEL_NOT_READY", "所需模型尚未就绪，请先完成模型与资产接入。")

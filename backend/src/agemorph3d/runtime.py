"""Lifespan-owned models, one CPU worker and bounded static asset publication."""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, TypeVar

from . import __version__
from .asset_cache import (
    AssetCache,
    AssetCacheClosed,
    AssetCapacityError,
    AssetLease,
    AssetNotFound,
)
from .config import Settings
from .errors import ApiError
from .images import decode_image
from .model_lifecycle import ModelLifecycle
from .schemas import Capabilities, Health, Reconstruction, SourceAge

if TYPE_CHECKING:
    from .reconstruction import PreparedReconstruction

T = TypeVar("T")


class Runtime:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agemorph3d")
        self._active = False
        self._closed = False
        self._started = False
        self._initialization: asyncio.Future[None] | None = None
        self._shutdown: asyncio.Task[None] | None = None
        self._models = ModelLifecycle(self._settings)
        self._assets = AssetCache(
            max_bytes=self._settings.asset_cache_bytes,
            max_entries=self._settings.asset_cache_entries,
            ttl_seconds=self._settings.asset_ttl_seconds,
        )

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
        models = self._models.snapshot()
        geometry_ready = not self._closed and all(
            models[name].state == "ready" for name in ("detector", "reconstructor")
        )
        return Health(
            api_version="1.2",
            version=__version__,
            device="cpu",
            models=models,
            capabilities=Capabilities(
                reconstruction=geometry_ready,
                realtime=geometry_ready,
            ),
        )

    async def process_frame(self, data: bytes, budget_seconds: float) -> dict:
        """Use the same owned model pair/worker without building or caching a GLB."""

        def work():
            with decode_image(data, "image/jpeg", self._settings, frame=True) as image:
                models = self._models.reconstruction_models()
                if models is None:
                    raise model_not_ready()
                import numpy as np

                from .realtime import infer_realtime

                return infer_realtime(np.asarray(image).copy(), *models)

        result = await self.run(work, budget_seconds)
        if self._closed:
            raise model_not_ready()
        return result

    async def prepare_static(
        self, data: bytes, media_type: str, source_age: SourceAge, budget_seconds: float
    ) -> "PreparedReconstruction":
        def work():
            # Decode first even without models: input errors retain their contract.
            with decode_image(data, media_type, self._settings) as image:
                models = self._models.reconstruction_models()
                if models is None:
                    raise model_not_ready()
                import numpy as np

                from .reconstruction import reconstruct_static

                return reconstruct_static(np.asarray(image).copy(), *models, source_age)

        return await self.run(work, budget_seconds)

    def publish_static(self, prepared: "PreparedReconstruction") -> Reconstruction:
        """No await between final caller checks and atomic cache publication."""
        if self._closed:
            raise model_not_ready()
        try:
            mesh_id = self._assets.publish(prepared.glb)
        except AssetCapacityError:
            raise ApiError(429, "BUSY", "模型资产缓存已满，请等待读取完成或稍后重试。") from None
        except AssetCacheClosed:
            raise model_not_ready() from None
        return prepared.result.model_copy(update={"mesh_id": mesh_id})

    def acquire_mesh(self, mesh_id: str) -> AssetLease:
        try:
            return self._assets.acquire(mesh_id)
        except (AssetNotFound, AssetCacheClosed):
            raise ApiError(404, "ASSET_NOT_FOUND", "模型资产不存在或已过期，请重新重建。") from None

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
            self._assets.close()
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

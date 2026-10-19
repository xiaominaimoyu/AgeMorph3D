"""Exercise cancellation and admission while actual worker threads remain alive."""

import asyncio
from threading import Event

import pytest

from agemorph3d.errors import ApiError
from agemorph3d.runtime import Runtime


async def expect_busy(runtime: Runtime, work) -> None:
    with pytest.raises(ApiError) as caught:
        await runtime.run(work, timeout=1)
    assert caught.value.status_code == 429
    assert caught.value.code == "BUSY"


async def eventually_available(runtime: Runtime) -> None:
    async def probe() -> None:
        while True:
            try:
                assert await runtime.run(lambda: "available", timeout=1) == "available"
                return
            except ApiError as error:
                if error.code != "BUSY":
                    raise
                await asyncio.sleep(0)

    await asyncio.wait_for(probe(), timeout=1)


async def test_only_one_worker_job_is_admitted_at_a_time() -> None:
    runtime = Runtime()
    started, release, second_called = Event(), Event(), Event()

    def first() -> str:
        started.set()
        assert release.wait(5)
        return "first-result"

    task = asyncio.create_task(runtime.run(first, timeout=2))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        await expect_busy(runtime, second_called.set)
        assert not second_called.is_set()
        assert runtime.health().capabilities.realtime is False
        release.set()
        assert await task == "first-result"
        assert await runtime.run(lambda: "next-result", timeout=1) == "next-result"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await runtime.close()


async def test_timeout_holds_slot_until_real_worker_finishes() -> None:
    runtime = Runtime()
    started, release, second_called = Event(), Event(), Event()

    def first() -> None:
        started.set()
        assert release.wait(5)

    try:
        with pytest.raises(ApiError) as caught:
            await runtime.run(first, timeout=0.05)
        assert started.is_set()
        assert caught.value.status_code == 504
        assert caught.value.code == "TIMEOUT"
        await expect_busy(runtime, second_called.set)
        assert not second_called.is_set()
        release.set()
        await eventually_available(runtime)
    finally:
        release.set()
        await runtime.close()


async def test_caller_cancellation_holds_slot_until_real_worker_finishes() -> None:
    runtime = Runtime()
    started, release, second_called = Event(), Event(), Event()

    def first() -> None:
        started.set()
        assert release.wait(5)

    task = asyncio.create_task(runtime.run(first, timeout=2))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await expect_busy(runtime, second_called.set)
        assert not second_called.is_set()
        release.set()
        await eventually_available(runtime)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await runtime.close()


async def test_worker_failure_releases_slot_and_propagates() -> None:
    runtime = Runtime()

    def fail() -> None:
        raise ValueError("test worker failure")

    try:
        with pytest.raises(ValueError, match="test worker failure"):
            await runtime.run(fail, timeout=1)
        assert await runtime.run(lambda: 7, timeout=1) == 7
    finally:
        await runtime.close()


async def test_close_drains_worker_and_prevents_new_jobs() -> None:
    runtime = Runtime()
    started, release, later_called = Event(), Event(), Event()

    def first() -> str:
        started.set()
        assert release.wait(5)
        return "finished"

    task = asyncio.create_task(runtime.run(first, timeout=2))
    shutdown = None
    try:
        assert await asyncio.to_thread(started.wait, 1)
        shutdown = asyncio.create_task(runtime.close())
        await asyncio.sleep(0)
        assert not shutdown.done()
        with pytest.raises(ApiError) as caught:
            await runtime.run(later_called.set, timeout=1)
        assert caught.value.status_code == 503
        assert not later_called.is_set()
        release.set()
        assert await task == "finished"
        await asyncio.wait_for(shutdown, timeout=1)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        if shutdown is not None:
            await shutdown
        else:
            await runtime.close()

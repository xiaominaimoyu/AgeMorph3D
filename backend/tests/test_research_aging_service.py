"""Synthetic service ownership only; opaque fixture bytes are not real PNG/GLB/model evidence."""

import asyncio
import hashlib
import threading
from dataclasses import replace

import pytest
from agemorph3d.aging_sessions import (
    AgingSessionCache,
    SessionCapacityError,
    SessionResult,
    SessionSource,
)
from agemorph3d.asset_cache import AssetCache, AssetCapacityError, AssetNotFound
from agemorph3d.errors import ApiError
from agemorph3d.research_aging_pipeline import (
    RegisteredConditionResult,
    StagedPreview,
    StagedTarget,
    _drain,
    source_fingerprint,
)
from agemorph3d.research_aging_service import ResearchAgingService
from agemorph3d.schemas import SourceAge

KNOWN = SourceAge(value=42.5, method="user", calibration_id=None)
UNKNOWN = SourceAge(value=None, method="unknown", calibration_id=None)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def opaque_source(image=b"synthetic-image", age=KNOWN):
    """Cache-contract bytes only; this fixture deliberately does not claim decoded geometry."""
    return SessionSource(
        age.model_dump_json().encode(),
        b"opaque-synthetic-rgb:" + image,
        b"opaque-synthetic-aligned:" + image,
        b"opaque-synthetic-correspondence:" + image,
        b"opaque-synthetic-glb:" + image,
        b"opaque-synthetic-texture:" + image,
        (0.1, 0.2),
    )


async def eventually(predicate):
    loop, ready, handle = asyncio.get_running_loop(), asyncio.Event(), None

    def check():
        nonlocal handle
        if predicate():
            ready.set()
        else:
            handle = loop.call_later(0.001, check)

    check()
    try:
        await asyncio.wait_for(ready.wait(), 3)
    finally:
        if handle is not None:
            handle.cancel()


class NativeGate:
    """Observe actual background-thread overlap without asserting model performance."""

    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.maximum = 0

    def enter(self):
        with self.lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)

    def leave(self):
        with self.lock:
            self.active -= 1


class SyntheticBuilder:
    def __init__(self, gate=None, *, blocked=False):
        self.gate = gate or NativeGate()
        self.entered, self.release = threading.Event(), threading.Event()
        if not blocked:
            self.release.set()
        self.calls = []
        self.sources = []
        self.closed = False

    def __call__(self, image, content_type, age):
        self.gate.enter()
        self.calls.append((image, content_type, age))
        self.entered.set()
        try:
            assert self.release.wait(3), "test failed to release synthetic source builder"
            source = opaque_source(image, age)
            self.sources.append(source)
            return source
        finally:
            self.gate.leave()

    def close(self):
        # The service must leave reconstruction/model ownership with this caller.
        self.closed = True


class SyntheticProcessor:
    """Duck-shaped controlled native work; no decoder, reconstruction or SAM runs."""

    def __init__(self, gate=None):
        self.gate = gate or NativeGate()
        self.calls = []
        self.handles = {}
        self.previews = {}
        self.blocked = None
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()
        self.pending = set()
        self.closed = False
        self.close_calls = 0
        self.sweep_calls = 0

    @property
    def snapshot(self):
        return {
            "closed": self.closed,
            "active": bool(self.pending),
            "native_cpu_active": bool(self.pending),
            "stage_index_entries": len(self.handles),
            "research_only": True,
            "service_ready": False,
        }

    def block(self, operation):
        self.blocked = operation
        self.entered.clear()
        self.release.clear()

    async def native(self, operation, function):
        def run():
            self.gate.enter()
            try:
                if self.blocked == operation:
                    self.entered.set()
                    assert self.release.wait(3), "test failed to release synthetic target work"
                return function()
            finally:
                self.gate.leave()

        task = asyncio.create_task(asyncio.to_thread(run))
        self.pending.add(task)
        try:
            return await _drain(task)
        finally:
            self.pending.discard(task)

    async def stage_condition(self, source, condition):
        self.calls.append(("stage", condition))
        key = (source_fingerprint(source), condition)
        if key in self.handles:
            return self.handles[key]

        def stage():
            index = len(self.previews) + 1
            png, fit = f"opaque-preview-{index}".encode(), f"opaque-fit-{index}".encode()
            handle = StagedTarget(f"{index:032x}", key[0], condition, sha(png), sha(fit))
            self.handles[key] = handle
            self.previews[handle.stage_id] = StagedPreview(handle, png, fit, ((0.0, 0.0),) * 68)
            return handle

        return await self.native("stage", stage)

    def check_staged(self, handle):
        if handle.stage_id not in self.previews:
            raise ApiError(404, "STAGE_EXPIRED", "Synthetic stage is absent.")

    def preview_staged(self, handle):
        if handle.stage_id not in self.previews:
            raise ApiError(404, "STAGE_EXPIRED", "Synthetic stage is absent.")
        return self.previews[handle.stage_id]

    async def register_reviewed(self, source, handle, review):
        self.calls.append(("register", handle.target_condition))
        if review is None:
            raise ApiError(409, "REVIEW_REQUIRED", "Synthetic review was not supplied.")

        def registered():
            condition = handle.target_condition
            return RegisteredConditionResult(
                SessionResult(
                    f"opaque-result-glb-{condition}".encode(),
                    f"opaque-result-texture-{condition}".encode(),
                    source.shape,
                    "synthetic_contract",
                ),
                b'{"scope":"synthetic service contract only"}',
            )

        return await self.native("register", registered)

    async def __call__(self, source, age):
        self.calls.append(("absolute", age))
        return await self.native(
            "absolute",
            lambda: SessionResult(
                f"opaque-absolute-glb-{age}".encode(),
                f"opaque-absolute-texture-{age}".encode(),
                source.shape,
                "synthetic_contract",
            ),
        )

    def sweep_stages(self):
        self.sweep_calls += 1

    async def close(self):
        self.close_calls += 1
        self.closed = True
        if self.pending:
            await asyncio.gather(*tuple(self.pending), return_exceptions=True)
        self.handles.clear()
        self.previews.clear()
        return self.snapshot


async def create_source(service, *, image=b"synthetic-image", age=KNOWN):
    return await service.create(image, "image/jpeg", age)


@pytest.mark.parametrize("abandonment", ["timeout", "cancel"])
async def test_abandoned_source_build_keeps_admission_and_never_publishes_session(abandonment):
    gate = NativeGate()
    builder, processor = SyntheticBuilder(gate, blocked=True), SyntheticProcessor(gate)
    cache = AgingSessionCache()
    service = ResearchAgingService(processor, builder, cache=cache)
    creating = asyncio.create_task(
        service.create(b"synthetic-image", "image/jpeg", KNOWN, timeout_seconds=0.02)
    )
    assert await asyncio.to_thread(builder.entered.wait, 2)
    try:
        if abandonment == "timeout":
            with pytest.raises(ApiError) as caught:
                await creating
            assert caught.value.code == "TIMEOUT"
        else:
            creating.cancel()
            with pytest.raises(asyncio.CancelledError):
                await creating
        assert service.snapshot()["active"] and gate.active == 1
        with pytest.raises(ApiError) as busy:
            await create_source(service, image=b"second-source")
        assert busy.value.code == "BUSY" and len(builder.calls) == 1
        builder.release.set()
        await eventually(lambda: not service.snapshot()["active"])
        assert cache.stats["entries"] == cache.stats["payload_bytes"] == 0
        assert gate.maximum == 1
    finally:
        builder.release.set()
        await asyncio.gather(creating, return_exceptions=True)
        await service.close()
    assert processor.closed and not builder.closed


@pytest.mark.parametrize("operation", ["stage", "register", "absolute"])
@pytest.mark.parametrize("abandonment", ["timeout", "cancel"])
async def test_abandoned_target_work_holds_source_pin_and_blocks_source_builder_until_native_done(
    operation, abandonment
):
    now, gate = [0.0], NativeGate()
    builder, processor = SyntheticBuilder(gate), SyntheticProcessor(gate)
    cache = AgingSessionCache(max_entries=1, ttl_seconds=1, clock=lambda: now[0])
    service = ResearchAgingService(processor, builder, cache=cache)
    identifier = await create_source(service)
    handle = await service.stage(identifier, 20) if operation == "register" else None
    processor.block(operation)
    if operation == "stage":
        call = service.stage(identifier, 20, timeout_seconds=0.02)
    elif operation == "register":
        call = service.register(identifier, handle.stage_id, object(), timeout_seconds=0.02)
    else:
        call = service.absolute(identifier, 20, timeout_seconds=0.02)
    work = asyncio.create_task(call)
    assert await asyncio.to_thread(processor.entered.wait, 2)
    try:
        if abandonment == "timeout":
            with pytest.raises(ApiError) as caught:
                await work
            assert caught.value.code == "TIMEOUT"
        else:
            work.cancel()
            with pytest.raises(asyncio.CancelledError):
                await work
        assert cache.stats["pins"] == 1 and cache.stats["results"] == 0
        with pytest.raises(ApiError) as busy:
            await create_source(service, image=b"new-source-while-target-native-is-held")
        assert busy.value.code == "BUSY" and len(builder.calls) == 1
        now[0] = 2
        cache.sweep()
        assert cache.stats["pins"] == 1 and cache.stats["payload_bytes"] > 0
        with pytest.raises(SessionCapacityError):
            cache.publish(opaque_source(b"cannot-evict-native-owned-source"))
        processor.release.set()
        await eventually(lambda: not service.snapshot()["active"])
        assert cache.stats["pins"] == cache.stats["payload_bytes"] == cache.stats["results"] == 0
        assert gate.maximum == 1
    finally:
        processor.release.set()
        await asyncio.gather(work, return_exceptions=True)
        await service.close()


@pytest.mark.parametrize("operation", ["stage", "register"])
async def test_native_completion_after_source_ttl_cannot_publish_stage_or_registered_result(
    operation,
):
    now = [0.0]
    builder, processor = SyntheticBuilder(), SyntheticProcessor()
    cache = AgingSessionCache(ttl_seconds=1, clock=lambda: now[0])
    service = ResearchAgingService(processor, builder, cache=cache)
    identifier = await create_source(service)
    handle = await service.stage(identifier, 20) if operation == "register" else None
    processor.block(operation)
    call = (
        service.stage(identifier, 20)
        if operation == "stage"
        else service.register(identifier, handle.stage_id, object())
    )
    work = asyncio.create_task(call)
    assert await asyncio.to_thread(processor.entered.wait, 2)
    try:
        now[0] = 2
        cache.sweep()
        assert cache.stats["pins"] == 1
        processor.release.set()
        with pytest.raises(ApiError) as expired:
            await work
        assert expired.value.code == "SESSION_EXPIRED"
        assert cache.stats["results"] == cache.stats["pins"] == cache.stats["payload_bytes"] == 0
        with pytest.raises(ApiError):
            service.source_info(identifier)
    finally:
        processor.release.set()
        await asyncio.gather(work, return_exceptions=True)
        await service.close()


async def test_unknown_age_cannot_bypass_absolute_guard_even_after_reviewed_result_is_cached():
    builder, processor = SyntheticBuilder(), SyntheticProcessor()
    cache = AgingSessionCache()
    service = ResearchAgingService(processor, builder, cache=cache)
    try:
        identifier = await create_source(service, age=UNKNOWN)
        handle = await service.stage(identifier, 20)
        registered = await service.register(identifier, handle.stage_id, object())
        assert registered.result.kind == "synthetic_contract" and cache.stats["results"] == 1
        calls_before = list(processor.calls)
        with pytest.raises(ApiError) as rejected:
            await service.absolute(identifier, 20)
        assert rejected.value.code == "SOURCE_AGE_REQUIRED"
        assert processor.calls == calls_before
        with service.asset(identifier, "glb", condition=20) as download:
            assert download.data == registered.result.glb
        assert service.source_info(identifier)["source_age"] == UNKNOWN.model_dump()
    finally:
        await service.close()


async def test_fractional_source_reset_retains_original_bytes_before_integer_generation_rules():
    builder, processor = SyntheticBuilder(), SyntheticProcessor()
    service = ResearchAgingService(processor, builder)
    try:
        identifier = await create_source(service)
        source = builder.sources[0]
        reset = await service.absolute(identifier, 42.5)
        assert reset.kind == "source_reset" and reset.shape == source.shape
        assert reset.glb is source.glb and reset.texture_png is source.texture_png
        with pytest.raises(ApiError) as fractional:
            await service.absolute(identifier, 42.6)
        assert fractional.value.code == "INTEGER_AGE_REQUIRED" and processor.calls == []
    finally:
        await service.close()


async def test_stage_owner_binding_and_bounded_aliases_do_not_expose_another_source():
    processor = SyntheticProcessor()
    service = ResearchAgingService(processor, SyntheticBuilder(), max_stages=2)
    try:
        first = await create_source(service, image=b"source-one")
        second = await create_source(service, image=b"source-two")
        first_handle = await service.stage(first, 20)
        second_handle = await service.stage(second, 20)
        with pytest.raises(ApiError) as wrong_owner:
            service.preview(second, first_handle.stage_id)
        assert wrong_owner.value.code == "STAGE_EXPIRED"
        with pytest.raises(ApiError) as wrong_download_owner:
            service.asset(second, "preview", condition=first_handle.stage_id)
        assert wrong_download_owner.value.code == "STAGE_EXPIRED"
        with pytest.raises(ApiError) as wrong_register_owner:
            await service.register(second, first_handle.stage_id, object())
        assert wrong_register_owner.value.code == "STAGE_EXPIRED"
        assert not any(operation == "register" for operation, _ in processor.calls)
        latest = await service.stage(first, 70)
        assert service.snapshot()["stage_entries"] == 2
        with pytest.raises(ApiError) as evicted:
            service.preview(first, first_handle.stage_id)
        assert evicted.value.code == "STAGE_EXPIRED"
        assert service.preview(second, second_handle.stage_id).target == second_handle
        assert service.preview(first, latest.stage_id).target == latest
    finally:
        await service.close()


async def test_stage_native_cache_expiry_is_checked_before_preview_or_asset_download():
    processor = SyntheticProcessor()
    service = ResearchAgingService(processor, SyntheticBuilder())
    try:
        identifier = await create_source(service)
        handle = await service.stage(identifier, 20)
        del processor.previews[handle.stage_id]
        for access in (
            lambda: service.preview(identifier, handle.stage_id),
            lambda: service.asset(identifier, "fit", condition=handle.stage_id),
        ):
            with pytest.raises(ApiError) as expired:
                access()
            assert expired.value.code == "STAGE_EXPIRED"
        assert service.snapshot()["downloads"] == 0
    finally:
        await service.close()


async def test_same_native_handle_can_be_explicitly_owned_by_two_sessions_without_cross_access():
    processor = SyntheticProcessor()
    service = ResearchAgingService(processor, SyntheticBuilder())
    try:
        first, second, unstaged = [await create_source(service) for _ in range(3)]
        first_handle = await service.stage(first, 20)
        second_handle = await service.stage(second, 20)
        assert first_handle == second_handle and len(processor.previews) == 1
        assert service.snapshot()["stage_entries"] == 2
        assert service.preview(first, first_handle.stage_id).target == first_handle
        assert service.preview(second, second_handle.stage_id).target == second_handle
        for identifier in (first, second):
            with service.asset(identifier, "fit", condition=first_handle.stage_id) as fit:
                assert fit.data == processor.previews[first_handle.stage_id].fit_bytes
        with pytest.raises(ApiError) as missing_ownership:
            service.preview(unstaged, first_handle.stage_id)
        assert missing_ownership.value.code == "STAGE_EXPIRED"
        with pytest.raises(ApiError) as unowned_registration:
            await service.register(unstaged, first_handle.stage_id, object())
        assert unowned_registration.value.code == "STAGE_EXPIRED"
        assert not any(operation == "register" for operation, _ in processor.calls)
    finally:
        await service.close()


async def test_four_download_slots_pin_original_bytes_and_close_is_idempotent():
    processor, builder = SyntheticProcessor(), SyntheticBuilder()
    cache = AgingSessionCache()
    service = ResearchAgingService(processor, builder, cache=cache, max_downloads=4)
    downloads = []
    try:
        identifier = await create_source(service)
        downloads = [service.asset(identifier, "source_glb") for _ in range(4)]
        assert service.snapshot()["downloads"] == cache.stats["pins"] == 4
        assert all(download.data is builder.sources[0].glb for download in downloads)
        with pytest.raises(ApiError) as full:
            service.asset(identifier, "source_texture")
        assert full.value.code == "BUSY"
        assert service.snapshot()["downloads"] == cache.stats["pins"] == 4
        downloads[0].close()
        downloads[0].close()
        assert service.snapshot()["downloads"] == cache.stats["pins"] == 3
        with service.asset(identifier, "source_texture") as texture:
            assert texture.data is builder.sources[0].texture_png
            assert cache.stats["pins"] == 4
        assert cache.stats["pins"] == 3
    finally:
        for download in downloads:
            download.close()
        await service.close()
    assert cache.stats["pins"] == service.snapshot()["downloads"] == 0


async def test_cancelled_stream_consumer_releases_download_slot_and_source_lease():
    cache = AgingSessionCache()
    service = ResearchAgingService(SyntheticProcessor(), SyntheticBuilder(), cache=cache)
    identifier = await create_source(service)
    entered, wait = asyncio.Event(), asyncio.Event()

    async def consumer():
        with service.asset(identifier, "source_glb") as download:
            assert download.data
            entered.set()
            await wait.wait()

    consuming = asyncio.create_task(consumer())
    await entered.wait()
    try:
        assert cache.stats["pins"] == service.snapshot()["downloads"] == 1
        consuming.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consuming
        assert cache.stats["pins"] == service.snapshot()["downloads"] == 0
    finally:
        consuming.cancel()
        await asyncio.gather(consuming, return_exceptions=True)
        await service.close()


async def test_expired_source_download_keeps_bytes_charged_until_lease_closes():
    now = [0.0]
    cache = AgingSessionCache(max_entries=1, ttl_seconds=1, clock=lambda: now[0])
    service = ResearchAgingService(SyntheticProcessor(), SyntheticBuilder(), cache=cache)
    download = None
    try:
        identifier = await create_source(service)
        download = service.asset(identifier, "source_glb")
        expected = download.data
        now[0] = 2
        cache.sweep()
        with pytest.raises(ApiError) as expired:
            service.source_info(identifier)
        assert expired.value.code == "SESSION_EXPIRED"
        assert download.data is expected and cache.stats["pins"] == 1
        with pytest.raises(SessionCapacityError):
            cache.publish(opaque_source(b"cannot-evict-an-open-download"))
        download.close()
        assert cache.stats["pins"] == cache.stats["payload_bytes"] == 0
    finally:
        if download is not None:
            download.close()
        await service.close()


async def test_cancelling_close_waiter_keeps_cleanup_running_and_leaves_builder_caller_owned():
    processor, builder = SyntheticProcessor(), SyntheticBuilder()
    service = ResearchAgingService(processor, builder)
    identifier = await create_source(service)
    processor.block("stage")
    staging = asyncio.create_task(service.stage(identifier, 20))
    assert await asyncio.to_thread(processor.entered.wait, 2)
    closing = asyncio.create_task(service.close())
    try:
        await eventually(lambda: service.snapshot()["closed"])
        closing.cancel()
        await asyncio.sleep(0)
        assert processor.pending and not builder.closed
        with pytest.raises(ApiError) as closed:
            await create_source(service)
        assert closed.value.code == "MODEL_NOT_READY"
        processor.release.set()
        await asyncio.gather(staging, return_exceptions=True)
        with pytest.raises(asyncio.CancelledError):
            await closing
        await service.close()
        assert processor.closed and not builder.closed
        assert not service.snapshot()["active"]
        assert service.snapshot()["cache"]["pins"] == 0
    finally:
        processor.release.set()
        await asyncio.gather(staging, closing, return_exceptions=True)
        await service.close()


async def test_periodic_sweeper_expires_idle_sessions_and_cleans_stage_aliases():
    now = [0.0]
    cache = AgingSessionCache(ttl_seconds=1, clock=lambda: now[0])
    processor = SyntheticProcessor()
    service = ResearchAgingService(processor, SyntheticBuilder(), cache=cache)
    try:
        identifier = await create_source(service)
        await service.stage(identifier, 20)
        await service.start(0.005)
        now[0] = 2
        await eventually(lambda: cache.stats["entries"] == 0)
        await eventually(lambda: service.snapshot()["stage_entries"] == 0)
        assert processor.sweep_calls > 0
    finally:
        await service.close()


async def test_service_close_keeps_open_download_bytes_charged_until_consumer_release():
    cache = AgingSessionCache()
    service = ResearchAgingService(SyntheticProcessor(), SyntheticBuilder(), cache=cache)
    identifier = await create_source(service)
    download = service.asset(identifier, "source_glb")
    expected = download.data
    try:
        await service.close()
        assert download.data is expected
        assert cache.stats["pins"] == service.snapshot()["downloads"] == 1
        assert cache.stats["payload_bytes"] > 0
        download.close()
        assert cache.stats["pins"] == cache.stats["payload_bytes"] == 0
        assert service.snapshot()["downloads"] == 0
    finally:
        download.close()
        await service.close()


async def test_source_builder_cannot_silently_fill_unknown_age():
    processor = SyntheticProcessor()
    service = ResearchAgingService(processor, lambda image, media, age: opaque_source(image, KNOWN))
    try:
        with pytest.raises(ApiError) as reassigned:
            await create_source(service, age=UNKNOWN)
        assert reassigned.value.code == "INVALID_CONTEXT"
        assert service.snapshot()["cache"]["entries"] == 0
        assert not service.snapshot()["active"]
    finally:
        await service.close()


@pytest.mark.parametrize("code", ["NO_FACE", "MULTI_FACE"])
async def test_source_builder_face_errors_remain_explicit_without_leaking_cache_or_admission(code):
    def fail_face(image, media, age):
        raise ApiError(422, code, "Synthetic controlled face failure.")

    service = ResearchAgingService(SyntheticProcessor(), fail_face)
    try:
        with pytest.raises(ApiError) as face_error:
            await create_source(service)
        assert face_error.value.code == code
        assert service.snapshot()["cache"]["entries"] == 0
        assert not service.snapshot()["active"]
    finally:
        await service.close()


@pytest.mark.parametrize("operation", ["create", "stage", "register", "absolute"])
async def test_cancellation_scheduled_by_native_completion_cannot_publish_success(operation):
    work = None

    class CancellingProcessor(SyntheticProcessor):
        async def stage_condition(self, source, condition):
            target = await super().stage_condition(source, condition)
            if operation == "stage":
                asyncio.get_running_loop().call_soon(work.cancel)
            return target

        async def register_reviewed(self, source, handle, review):
            registered = await super().register_reviewed(source, handle, review)
            if operation == "register":
                asyncio.get_running_loop().call_soon(work.cancel)
            return registered

        async def __call__(self, source, age):
            result = await super().__call__(source, age)
            if operation == "absolute":
                asyncio.get_running_loop().call_soon(work.cancel)
            return result

    loop = asyncio.get_running_loop()

    def builder(image, media, age):
        if operation == "create":
            loop.call_soon_threadsafe(work.cancel)
        return opaque_source(image, age)

    service = ResearchAgingService(CancellingProcessor(), builder)
    if operation == "create":
        call = create_source(service)
    else:
        identifier = await create_source(service)
        if operation == "stage":
            call = service.stage(identifier, 20)
        elif operation == "register":
            handle = await service.stage(identifier, 20)
            call = service.register(identifier, handle.stage_id, object())
        else:
            call = service.absolute(identifier, 20)
    work = asyncio.create_task(call)
    try:
        with pytest.raises(asyncio.CancelledError):
            await work
        await eventually(lambda: not service.snapshot()["active"])
        snapshot = service.snapshot()
        assert snapshot["cache"]["results"] == 0
        if operation == "create":
            assert snapshot["cache"]["entries"] == 0
        elif operation in {"stage", "absolute"}:
            assert snapshot["stage_entries"] == 0
        else:
            assert snapshot["stage_entries"] == 1
    finally:
        await asyncio.gather(work, return_exceptions=True)
        await service.close()


async def test_source_native_reconstruction_blocks_target_native_and_releases_failed_request_pin():
    gate = NativeGate()
    builder, processor = SyntheticBuilder(gate), SyntheticProcessor(gate)
    cache = AgingSessionCache()
    service = ResearchAgingService(processor, builder, cache=cache)
    identifier = await create_source(service)
    builder.entered.clear()
    builder.release.clear()
    creating = asyncio.create_task(create_source(service, image=b"second-source"))
    assert await asyncio.to_thread(builder.entered.wait, 2)
    try:
        for call in (
            lambda: service.stage(identifier, 20),
            lambda: service.absolute(identifier, 20),
        ):
            with pytest.raises(ApiError) as busy:
                await call()
            assert busy.value.code == "BUSY"
            assert cache.stats["pins"] == 0
        assert processor.calls == [] and gate.maximum == 1
        builder.release.set()
        assert await creating
    finally:
        builder.release.set()
        await asyncio.gather(creating, return_exceptions=True)
        await service.close()


@pytest.mark.parametrize(
    ("kind", "condition", "code"),
    [
        ("not-an-asset", None, "RESULT_NOT_FOUND"),
        ("glb", 20, "RESULT_NOT_FOUND"),
        ("fit", "f" * 32, "STAGE_EXPIRED"),
    ],
)
async def test_failed_download_lookup_releases_both_slot_and_source_pin(kind, condition, code):
    cache = AgingSessionCache()
    service = ResearchAgingService(SyntheticProcessor(), SyntheticBuilder(), cache=cache)
    try:
        identifier = await create_source(service)
        with pytest.raises(ApiError) as missing:
            service.asset(identifier, kind, condition=condition)
        assert missing.value.code == code
        assert service.snapshot()["downloads"] == cache.stats["pins"] == 0
        with service.asset(identifier, "source_glb") as available:
            assert available.data
    finally:
        await service.close()


async def test_absolute_wrapper_completion_cancellation_cannot_commit_coordinator_result():
    processor = SyntheticProcessor()
    cache = AgingSessionCache()
    service = ResearchAgingService(processor, SyntheticBuilder(), cache=cache)
    identifier = await create_source(service)
    processor.block("absolute")
    generating = asyncio.create_task(service.absolute(identifier, 20))
    assert await asyncio.to_thread(processor.entered.wait, 2)
    # Cancel at Coordinator's actual wrapper completion, after its shield has
    # already attached callbacks. This exercises Python3.11's done-result race.
    wrapper = service.coordinator._active
    assert wrapper is not None and not wrapper.done()
    wrapper.add_done_callback(lambda _finished: generating.cancel())
    try:
        processor.release.set()
        with pytest.raises(asyncio.CancelledError):
            await generating
        assert generating.cancelling() > 0
        await eventually(lambda: not service.snapshot()["active"])
        assert cache.stats["results"] == cache.stats["pins"] == 0
        assert processor.calls == [("absolute", 20)]
    finally:
        processor.release.set()
        await asyncio.gather(generating, return_exceptions=True)
        await service.close()


class CacheBackedSyntheticProcessor(SyntheticProcessor):
    """Opaque stages in the real bounded cache; still no real PNG/GLB decoding."""

    def __init__(self, *, clock=None):
        super().__init__()
        options = {} if clock is None else {"clock": clock}
        self.stage_store = AssetCache(
            max_bytes=1024, max_entries=1, max_asset_bytes=1024, ttl_seconds=1, **options
        )
        self.fail_preview = False

    async def stage_condition(self, source, condition):
        self.calls.append(("stage", condition))
        key = (source_fingerprint(source), condition)
        if key in self.handles:
            with self._lease(self.handles[key]):
                return self.handles[key]

        def stage():
            png = f"opaque-preview-{condition}".encode()
            fit = f"opaque-fit-{condition}".encode()
            identifier = self.stage_store.publish(b"charged-synthetic-stage:" + png + fit)
            target = StagedTarget(identifier, key[0], condition, sha(png), sha(fit))
            self.handles[key] = target
            self.previews[identifier] = StagedPreview(target, png, fit, ((0.0, 0.0),) * 68)
            return target

        return await self.native("stage", stage)

    def check_staged(self, target):
        if not self.stage_store.contains_current(target.stage_id):
            raise ApiError(404, "STAGE_EXPIRED", "Synthetic charged stage expired.")

    def _lease(self, target):
        try:
            return self.stage_store.acquire(target.stage_id)
        except AssetNotFound:
            raise ApiError(404, "STAGE_EXPIRED", "Synthetic charged stage expired.") from None

    def preview_staged(self, target):
        with self._lease(target):
            if self.fail_preview:
                raise ValueError("synthetic preview decoding failure after stage acquisition")
            return super().preview_staged(target)

    async def close(self):
        try:
            return await super().close()
        finally:
            self.stage_store.close()


@pytest.mark.parametrize("kind", ["preview", "fit"])
async def test_stage_download_holds_real_stage_cache_pin_until_send_lease_closes(kind):
    processor = CacheBackedSyntheticProcessor()
    cache = AgingSessionCache()
    service = ResearchAgingService(processor, SyntheticBuilder(), cache=cache)
    download = None
    try:
        identifier = await create_source(service)
        target = await service.stage(identifier, 20)
        download = service.asset(identifier, kind, condition=target.stage_id)
        assert cache.stats["pins"] == service.snapshot()["downloads"] == 1
        with pytest.raises(AssetCapacityError):
            processor.stage_store.publish(b"cannot evict stage while preview or fit is being sent")
        expected = processor.previews[target.stage_id]
        assert download.data == (expected.png if kind == "preview" else expected.fit_bytes)
        download.close()
        download.close()
        assert cache.stats["pins"] == service.snapshot()["downloads"] == 0
        assert processor.stage_store.publish(b"the send lease released actual stage ownership")
    finally:
        if download is not None:
            download.close()
        await service.close()


@pytest.mark.parametrize("kind", ["preview", "fit"])
async def test_preview_decode_failure_releases_stage_source_and_download_slot(kind):
    processor = CacheBackedSyntheticProcessor()
    cache = AgingSessionCache()
    service = ResearchAgingService(processor, SyntheticBuilder(), cache=cache)
    try:
        identifier = await create_source(service)
        target = await service.stage(identifier, 20)
        processor.fail_preview = True
        with pytest.raises(ValueError, match="synthetic preview decoding failure"):
            service.asset(identifier, kind, condition=target.stage_id)
        assert cache.stats["pins"] == service.snapshot()["downloads"] == 0
        assert processor.stage_store.publish(b"no leaked stage pin after failed preview decode")
    finally:
        await service.close()


async def test_expired_stage_download_remains_charged_until_consumer_releases_pin():
    now = [0.0]
    processor = CacheBackedSyntheticProcessor(clock=lambda: now[0])
    service = ResearchAgingService(processor, SyntheticBuilder())
    download = None
    try:
        identifier = await create_source(service)
        target = await service.stage(identifier, 20)
        download = service.asset(identifier, "preview", condition=target.stage_id)
        expected = download.data
        now[0] = 2
        with pytest.raises(ApiError) as expired:
            service.preview(identifier, target.stage_id)
        assert expired.value.code == "STAGE_EXPIRED" and download.data is expected
        with pytest.raises(AssetCapacityError):
            processor.stage_store.publish(b"expired stage still has an active send lease")
        download.close()
        assert processor.stage_store.publish(b"expired stage budget released after send")
        assert service.snapshot()["downloads"] == 0
    finally:
        if download is not None:
            download.close()
        await service.close()


async def test_conflicting_review_result_is_rejected_without_changing_cached_downloads():
    class ReviewDependentProcessor(SyntheticProcessor):
        async def register_reviewed(self, source, handle, review):
            registered = await super().register_reviewed(source, handle, review)
            return replace(
                registered,
                result=replace(registered.result, glb=registered.result.glb + b":" + review),
            )

    cache = AgingSessionCache()
    service = ResearchAgingService(ReviewDependentProcessor(), SyntheticBuilder(), cache=cache)
    try:
        identifier = await create_source(service)
        target = await service.stage(identifier, 20)
        first = await service.register(identifier, target.stage_id, b"synthetic-review-one")
        same = await service.register(identifier, target.stage_id, b"synthetic-review-one")
        assert same.result == first.result and cache.stats["results"] == 1
        with pytest.raises(ApiError) as conflict:
            await service.register(identifier, target.stage_id, b"synthetic-review-two")
        assert conflict.value.status_code == 409 and conflict.value.code == "RESULT_CONFLICT"
        assert cache.stats["results"] == 1 and cache.stats["pins"] == 0
        with service.asset(identifier, "glb", condition=20) as cached:
            assert cached.data == first.result.glb
        with service.asset(identifier, "texture", condition=20) as texture:
            assert texture.data == first.result.texture_png
        retry = await service.register(identifier, target.stage_id, b"synthetic-review-one")
        assert retry.result == first.result
    finally:
        await service.close()


async def test_stage_check_is_owned_nonrenewing_and_does_not_download_or_start_native(monkeypatch):
    now = [0.0]
    processor = CacheBackedSyntheticProcessor(clock=lambda: now[0])
    cache = AgingSessionCache(ttl_seconds=10, clock=lambda: now[0])
    service = ResearchAgingService(processor, SyntheticBuilder(), cache=cache)
    try:
        first = await create_source(service, age=UNKNOWN)
        other = await create_source(service, image=b"other synthetic source", age=UNKNOWN)
        target = await service.stage(first, 45)
        native_calls = list(processor.calls)

        def forbidden(*args, **kwargs):
            pytest.fail("Status check attempted a preview decode or download.")

        monkeypatch.setattr(processor, "preview_staged", forbidden)
        monkeypatch.setattr(service, "asset", forbidden)
        monkeypatch.setattr("agemorph3d.research_aging_service.source_fingerprint", forbidden)
        for moment in (0.1, 0.7, 0.99):
            now[0] = moment
            assert service.check_stage(first, target.stage_id) == target
            assert processor.calls == native_calls
            assert cache.stats["pins"] == processor.stage_store._entries[target.stage_id].pins == 0
            assert service.snapshot()["downloads"] == 0
        with pytest.raises(ApiError) as caught:
            service.check_stage(other, target.stage_id)
        assert caught.value.code == "STAGE_EXPIRED"
        now[0] = 1
        with pytest.raises(ApiError) as caught:
            service.check_stage(first, target.stage_id)
        assert caught.value.code == "STAGE_EXPIRED" and processor.calls == native_calls
        with cache.acquire(first) as lease:
            assert lease.source.source_age.model_dump() == UNKNOWN.model_dump()
    finally:
        await service.close()


async def test_stage_check_rejects_expired_source_even_when_stage_storage_is_live():
    now = [0.0]
    processor = CacheBackedSyntheticProcessor(clock=lambda: now[0])
    cache = AgingSessionCache(ttl_seconds=0.5, clock=lambda: now[0])
    service = ResearchAgingService(processor, SyntheticBuilder(), cache=cache)
    try:
        sid = await create_source(service)
        target = await service.stage(sid, 45)
        now[0] = 0.5
        assert processor.stage_store.contains_current(target.stage_id)
        with pytest.raises(ApiError) as caught:
            service.check_stage(sid, target.stage_id)
        assert caught.value.code == "SESSION_EXPIRED"
        assert cache.stats["pins"] == processor.stage_store._entries[target.stage_id].pins == 0
    finally:
        await service.close()

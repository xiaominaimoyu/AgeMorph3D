"""Synthetic session, cache and abandonment contracts; no SAM or age-quality claims."""

import asyncio
import importlib.util
import json
import weakref
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from agemorph3d.aging_sessions import (
    AgingCoordinator,
    AgingSessionCache,
    SessionCapacityError,
    SessionClosed,
    SessionNotFound,
    SessionResult,
    SessionSource,
)
from agemorph3d.app import create_app
from agemorph3d.config import Settings
from agemorph3d.errors import ApiError


def source(age=42.5):
    return SessionSource(
        source_age_json=json.dumps(
            {
                "value": age,
                "method": "unknown" if age is None else "user",
                "calibration_id": None,
            }
        ).encode(),
        original_rgb=b"immutable-original-rgb",
        aligned_png=b"immutable-aligned-png",
        correspondence=b"immutable-fit-and-alignment-context",
        glb=b"exact-original-glb",
        texture_png=b"exact-original-texture",
        shape=(0.1, 0.2),
    )


def result(age=20):
    return SessionResult(
        f"glb-{age}".encode(), f"png-{age}".encode(), (0.1, 0.2), "synthetic_contract"
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
        await asyncio.wait_for(ready.wait(), 2)
    finally:
        if handle is not None:
            handle.cancel()


def test_immutable_original_context_and_source_reset_bytes_are_separate_from_derived_cache():
    original = source()
    with pytest.raises(FrozenInstanceError):
        original.glb = b"mutated"
    cache = AgingSessionCache()
    identifier = cache.publish(original)
    with cache.acquire(identifier) as lease:
        assert lease.source is original
        cache.remember(lease, 20, result())
        assert cache.get_result(lease, 20) == result()
        assert lease.source.glb == b"exact-original-glb"
    assert cache.stats["results"] == 1 and cache.stats["pins"] == 0
    cache.close()
    assert cache.stats["payload_bytes"] == 0


@pytest.mark.parametrize("change", ["mutable", "age", "shape", "kind"])
def test_invalid_mutable_or_unprovenanced_payloads_cannot_enter_cache(change):
    with pytest.raises(ValueError):
        if change == "mutable":
            replace(source(), original_rgb=bytearray(b"mutable"))
        elif change == "age":
            replace(
                source(), source_age_json=b'{"value":45,"method":"unknown","calibration_id":null}'
            )
        elif change == "shape":
            replace(source(), shape=(float("nan"),))
        else:
            replace(result(), kind="observed_real_age")


def test_fixed_ttl_applies_to_late_derived_results_and_never_extends_on_reads():
    now = [100.0]
    cache = AgingSessionCache(ttl_seconds=10, clock=lambda: now[0])
    identifier = cache.publish(source())
    now[0] = 109
    with cache.acquire(identifier) as lease:
        cache.remember(lease, 20, result())
        assert cache.get_result(lease, 20) == result()
    now[0] = 110
    with pytest.raises(SessionNotFound):
        cache.acquire(identifier)
    assert cache.stats["results"] == cache.stats["payload_bytes"] == 0


def test_pinned_expired_and_closed_payloads_remain_charged_until_actual_release():
    now = [100.0]
    original = source()
    cache = AgingSessionCache(
        max_bytes=original.payload_bytes, max_entries=1, ttl_seconds=10, clock=lambda: now[0]
    )
    identifier = cache.publish(original)
    lease = cache.acquire(identifier)
    now[0] = 110
    cache.sweep()
    with pytest.raises(SessionNotFound):
        cache.acquire(identifier)
    with pytest.raises(SessionCapacityError):
        cache.publish(source())
    assert lease.source.glb == original.glb
    cache.close()
    assert cache.stats["payload_bytes"] == original.payload_bytes and cache.stats["pins"] == 1
    lease.close()
    lease.close()
    assert cache.stats["payload_bytes"] == cache.stats["pins"] == 0
    with pytest.raises(SessionClosed):
        cache.publish(original)


def test_lru_eviction_and_failed_capacity_attempt_preserve_pinned_source():
    original = source()
    cache = AgingSessionCache(max_bytes=original.payload_bytes * 2, max_entries=2)
    first, second = cache.publish(original), cache.publish(original)
    with cache.acquire(first):
        third = cache.publish(original)
        with pytest.raises(SessionNotFound):
            cache.acquire(second)
        with cache.acquire(third):
            with pytest.raises(SessionCapacityError):
                cache.publish(original)
    assert cache.stats["entries"] == 2
    cache.close()


async def test_fractional_source_exact_reset_precedes_integer_gate_and_never_calls_processor():
    cache = AgingSessionCache()
    original = source()
    identifier = cache.publish(original)

    async def forbidden(*args):
        pytest.fail("Exact source reset must bypass generation")

    coordinator = AgingCoordinator(cache, forbidden)
    reset = await coordinator.generate(identifier, 42.5)
    assert reset.kind == "source_reset"
    assert reset.glb is original.glb and reset.texture_png is original.texture_png
    assert cache.stats["results"] == 0
    await coordinator.close()


@pytest.mark.parametrize(
    "age,expected", [(None, "SOURCE_AGE_REQUIRED"), (42.6, "INTEGER_AGE_REQUIRED")]
)
async def test_unknown_and_noninteger_absolute_requests_fail_without_generation(age, expected):
    cache = AgingSessionCache()
    identifier = cache.publish(source(None if age is None else 42.5))

    async def forbidden(*args):
        pytest.fail("Unsupported requests cannot silently default or round")

    coordinator = AgingCoordinator(cache, forbidden)
    with pytest.raises(ApiError) as caught:
        await coordinator.generate(identifier, 20 if age is None else age)
    assert caught.value.code == expected
    assert cache.stats["pins"] == 0
    await coordinator.close()


async def test_integer_generation_is_cached_and_every_target_uses_original_source():
    cache = AgingSessionCache()
    original = source()
    identifier = cache.publish(original)
    calls = []

    async def processor(context, age):
        calls.append((context, age))
        return result(age)

    coordinator = AgingCoordinator(cache, processor)
    assert (await coordinator.generate(identifier, 20)).kind == "synthetic_contract"
    assert await coordinator.generate(identifier, 20.0) == result(20)
    assert await coordinator.generate(identifier, 70) == result(70)
    assert [age for _, age in calls] == [20, 70]
    assert all(context is original for context, _ in calls)
    await coordinator.close()


@pytest.mark.parametrize("abandon", ["timeout", "cancel"])
async def test_abandoned_processing_keeps_admission_and_session_pin_until_real_completion(abandon):
    cache = AgingSessionCache(max_entries=1)
    identifier = cache.publish(source())
    entered, release = asyncio.Event(), asyncio.Event()

    async def processor(context, age):
        entered.set()
        await release.wait()
        return result(age)

    coordinator = AgingCoordinator(cache, processor)
    waiter = asyncio.create_task(
        coordinator.generate(identifier, 20, timeout_seconds=0.01 if abandon == "timeout" else 5)
    )
    await entered.wait()
    if abandon == "cancel":
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
    else:
        with pytest.raises(ApiError) as caught:
            await waiter
        assert caught.value.code == "TIMEOUT"
    assert cache.stats["pins"] == 1
    with pytest.raises(SessionCapacityError):
        cache.publish(source())
    with pytest.raises(ApiError) as caught:
        await coordinator.generate(identifier, 70)
    assert caught.value.code == "BUSY"
    release.set()
    await eventually(lambda: cache.stats["pins"] == 0)
    assert cache.stats["results"] == 0
    assert await coordinator.generate(identifier, 70) == result(70)
    await coordinator.close()


async def test_expiry_during_processor_discards_late_result_and_remains_recoverable():
    now = [100.0]
    cache = AgingSessionCache(ttl_seconds=10, clock=lambda: now[0])
    identifier = cache.publish(source())
    entered, release = asyncio.Event(), asyncio.Event()

    async def processor(context, age):
        entered.set()
        await release.wait()
        return result(age)

    coordinator = AgingCoordinator(cache, processor)
    waiter = asyncio.create_task(coordinator.generate(identifier, 20))
    await entered.wait()
    now[0] = 110
    release.set()
    with pytest.raises(ApiError) as caught:
        await waiter
    assert caught.value.code == "SESSION_EXPIRED"
    assert cache.stats["results"] == cache.stats["pins"] == 0
    replacement = cache.publish(source())
    assert (await coordinator.generate(replacement, 42.5)).kind == "source_reset"
    await coordinator.close()


async def test_shutdown_drains_processor_despite_shutdown_waiter_cancellation():
    cache = AgingSessionCache()
    identifier = cache.publish(source())
    entered, release = asyncio.Event(), asyncio.Event()

    async def processor(context, age):
        entered.set()
        await release.wait()
        return result(age)

    coordinator = AgingCoordinator(cache, processor)
    waiter = asyncio.create_task(coordinator.generate(identifier, 20))
    await entered.wait()
    shutdown = asyncio.create_task(coordinator.close())
    await asyncio.sleep(0)
    assert not shutdown.done() and cache.stats["pins"] == 1
    shutdown.cancel()
    with pytest.raises(asyncio.CancelledError):
        await shutdown
    with pytest.raises(ApiError) as caught:
        await coordinator.generate(identifier, 70)
    assert caught.value.code == "MODEL_NOT_READY"
    release.set()
    with pytest.raises(ApiError) as caught:
        await waiter
    assert caught.value.code == "MODEL_NOT_READY"
    await coordinator.close()
    assert cache.stats["payload_bytes"] == 0


async def test_processor_failure_releases_slot_and_does_not_cache_failure():
    cache = AgingSessionCache()
    identifier = cache.publish(source())
    calls = []

    async def processor(context, age):
        calls.append(age)
        if len(calls) == 1:
            raise RuntimeError("Synthetic processor failure")
        return result(age)

    coordinator = AgingCoordinator(cache, processor)
    with pytest.raises(RuntimeError):
        await coordinator.generate(identifier, 20)
    assert cache.stats["results"] == cache.stats["pins"] == 0
    assert await coordinator.generate(identifier, 20) == result(20)
    await coordinator.close()


async def test_production_app_stays_closed_without_synthetic_fixture():
    import httpx

    app = create_app(Settings())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            response = await client.post("/api/aging", json={"mesh_id": "synthetic", "age": 20})
            assert response.status_code == 503 and response.json()["code"] == "MODEL_NOT_READY"
            flags = (await client.get("/api/health")).json()["capabilities"]
            assert flags["age_morph"] is flags["age_texture"] is False


async def test_sweeper_releases_idle_expired_context_without_any_further_cache_request():
    now = [100.0]
    cache = AgingSessionCache(ttl_seconds=10, clock=lambda: now[0])
    original = source()
    retained = weakref.ref(original)
    cache.publish(original)
    del original

    async def forbidden(*args):
        pytest.fail("Sweeping must not trigger generation")

    coordinator = AgingCoordinator(cache, forbidden)
    await coordinator.start(sweep_interval_seconds=0.001)
    now[0] = 110
    # Weak references do not call stats/acquire/sweep, so only the owned timer can purge it.
    await eventually(lambda: retained() is None)
    await coordinator.close()


def fixture_module():
    path = Path(__file__).parent / "fixtures" / "aging_contract_app.py"
    spec = importlib.util.spec_from_file_location("aging_contract_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("missing", ["marker", "nonce"])
def test_synthetic_factory_requires_explicit_test_marker_and_owner_nonce(monkeypatch, missing):
    monkeypatch.setenv("AGEMORPH_SYNTHETIC_AGING_CONTRACT", "1")
    monkeypatch.setenv("AGEMORPH_SYNTHETIC_NONCE", "ab" * 24)
    monkeypatch.delenv(
        "AGEMORPH_SYNTHETIC_AGING_CONTRACT" if missing == "marker" else "AGEMORPH_SYNTHETIC_NONCE",
        raising=False,
    )
    with pytest.raises(RuntimeError, match="test-only" if missing == "marker" else "random nonce"):
        fixture_module().create_app()


def test_parent_monitor_requires_fixture_flag_and_never_changes_production_factory(monkeypatch):
    module = fixture_module()
    calls = []

    def monitor():
        calls.append("fixture-parent-handle")
        return True

    monkeypatch.setattr(module, "_windows_parent_monitor", monitor)
    monkeypatch.setenv("AGEMORPH_SYNTHETIC_AGING_CONTRACT", "1")
    monkeypatch.setenv("AGEMORPH_SYNTHETIC_NONCE", "ab" * 24)
    monkeypatch.delenv("AGEMORPH_SYNTHETIC_PARENT_MONITOR", raising=False)
    module.create_app()
    assert calls == []
    monkeypatch.setenv("AGEMORPH_SYNTHETIC_PARENT_MONITOR", "1")
    module.create_app()
    assert calls == (["fixture-parent-handle"] if module.os.name == "nt" else [])
    before = calls.copy()
    production = create_app(Settings())
    assert calls == before
    assert not any(
        getattr(route, "path", "").startswith("/_contract") for route in production.routes
    )


async def test_synthetic_http_contract_cache_reset_expiry_and_production_boundary(monkeypatch):
    import httpx

    monkeypatch.setenv("AGEMORPH_SYNTHETIC_AGING_CONTRACT", "1")
    monkeypatch.setenv("AGEMORPH_SYNTHETIC_NONCE", "ab" * 24)
    app = fixture_module().create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            photo = (await client.get("/_contract/input.png")).content
            ownership = (await client.get("/_contract/state")).json()
            assert ownership["fixture_nonce"] == "ab" * 24
            assert ownership["fixture_pid"] > 0 and ownership["fixture_ppid"] > 0

            async def reconstruct():
                response = await client.post(
                    "/api/reconstruct",
                    data={"source_age": "42.5"},
                    files={"image": ("synthetic.png", photo, "image/png")},
                )
                assert response.status_code == 200, response.text
                return response.json()

            metadata = await reconstruct()
            identifier = metadata["mesh_id"]
            base = (await client.get(metadata["texture_url"])).content
            for _ in range(2):
                generated = await client.post("/api/aging", json={"mesh_id": identifier, "age": 20})
                assert generated.status_code == 200, generated.text
                assert generated.json()["kind"] == "synthetic_contract"
            assert (await client.get("/_contract/state")).json()["calls"] == [20]
            reset = await client.post("/api/aging", json={"mesh_id": identifier, "age": 42.5})
            assert reset.json()["kind"] == "source_reset"
            assert (await client.get(reset.json()["texture_url"])).content == base
            await client.post("/_contract/advance", json={"seconds": 300})
            assert (await client.get(generated.json()["texture_url"])).status_code == 404
            expired = await client.post("/api/aging", json={"mesh_id": identifier, "age": 20})
            assert expired.status_code == 404 and expired.json()["code"] == "SESSION_EXPIRED"
            assert (await reconstruct())["mesh_id"] != identifier
            production = (await client.get("/_contract/production-probe")).json()
            assert (
                production["aging_status"] == 503 and production["aging_code"] == "MODEL_NOT_READY"
            )
            assert production["age_morph"] is production["age_texture"] is False

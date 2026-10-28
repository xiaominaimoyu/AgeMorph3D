"""Behavioral coverage for generated-byte retention, never real GLB acceptance."""

import math
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from agemorph3d.asset_cache import (
    AssetCache,
    AssetCacheClosed,
    AssetCapacityError,
    AssetNotFound,
)


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def test_current_metadata_checks_never_pin_renew_or_promote_lru():
    clock = Clock()
    cache = AssetCache(max_bytes=3, max_asset_bytes=1, max_entries=2, ttl_seconds=10, clock=clock)
    first, second = cache.publish(b"a"), cache.publish(b"b")
    for moment in (1, 5, 9):
        clock.value = moment
        assert cache.contains_current(first)
        assert cache._entries[first].pins == 0
    third = cache.publish(b"c")
    assert not cache.contains_current(first), "Checking must not protect the oldest LRU entry."
    assert cache.contains_current(second) and cache.contains_current(third)
    clock.value = 10
    assert not cache.contains_current(second)
    assert cache.contains_current(third)


def test_metadata_expiry_rejects_pinned_retained_bytes_without_releasing_the_owner():
    clock = Clock()
    cache = AssetCache(ttl_seconds=1, clock=clock)
    identifier = cache.publish(b"retained")
    lease = cache.acquire(identifier)
    clock.value = 1
    assert not cache.contains_current(identifier)
    assert lease.data == b"retained" and cache._entries[identifier].pins == 1
    lease.close()
    assert cache._entries == {} and cache._retained_bytes == 0


@pytest.mark.parametrize("identifier", [None, True, 1, "", "a" * 31, "G" * 32])
def test_invalid_metadata_id_is_unavailable(identifier):
    cache = AssetCache()
    assert cache.contains_current(identifier) is False


def test_closed_metadata_cache_cannot_report_available():
    cache = AssetCache()
    identifier = cache.publish(b"data")
    cache.close()
    with pytest.raises(AssetCacheClosed):
        cache.contains_current(identifier)


@pytest.mark.parametrize("name", ["max_bytes", "max_entries", "max_asset_bytes"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, math.inf, math.nan, "8", None])
def test_invalid_integer_budgets(name: str, value: object) -> None:
    with pytest.raises(ValueError):
        AssetCache(**{name: value})


@pytest.mark.parametrize("value", [0, -1, True, math.inf, -math.inf, math.nan, "8", None])
def test_invalid_ttl(value: object) -> None:
    with pytest.raises(ValueError):
        AssetCache(ttl_seconds=value)


def test_invalid_clock() -> None:
    with pytest.raises(ValueError):
        AssetCache(clock=None)
    for value in [True, math.inf, math.nan, "1"]:
        cache = AssetCache(clock=lambda value=value: value)
        with pytest.raises(ValueError):
            cache.publish(b"glb")


@pytest.mark.parametrize("value", [bytearray(b"glb"), memoryview(b"glb"), "glb", None])
def test_only_immutable_bytes_are_accepted(value: object) -> None:
    with pytest.raises(TypeError):
        AssetCache().publish(value)


def test_empty_asset_is_rejected() -> None:
    with pytest.raises(ValueError):
        AssetCache().publish(b"")


def test_unpredictable_ids_and_exact_immutable_payloads() -> None:
    cache = AssetCache(max_entries=128)
    identifiers = [cache.publish(b"identical GLB fixture bytes") for _ in range(128)]
    assert len(set(identifiers)) == 128
    assert all(re.fullmatch(r"[0-9a-f]{32}", mesh_id) for mesh_id in identifiers)
    for mesh_id in identifiers:
        with cache.acquire(mesh_id) as lease:
            assert lease.data == b"identical GLB fixture bytes"


@pytest.mark.parametrize(
    "identifier",
    [
        "../model.glb",
        "a" * 32 + "/..",
        "%2e%2e%2fmodel.glb",
        "A" * 32,
        "a" * 31,
        "a" * 33,
        "a" * 32 + "\n",
        "Ｄ" * 32,
        "",
        None,
    ],
)
def test_invalid_identifiers_have_one_public_safe_failure(identifier: object) -> None:
    with pytest.raises(AssetNotFound, match=r"^Asset not found\.$"):
        AssetCache().acquire(identifier)


def test_unknown_identifier() -> None:
    with pytest.raises(AssetNotFound):
        AssetCache().acquire("0" * 32)


def test_ttl_deadline_is_absolute_even_after_reads() -> None:
    clock = Clock()
    cache = AssetCache(ttl_seconds=10, clock=clock)
    mesh_id = cache.publish(b"glb")
    clock.value = 9.9
    with cache.acquire(mesh_id) as lease:
        assert lease.data == b"glb"
    clock.value = 10
    with pytest.raises(AssetNotFound):
        cache.acquire(mesh_id)


def test_lru_eviction_uses_reads_and_entry_limit() -> None:
    cache = AssetCache(max_entries=2)
    first = cache.publish(b"first")
    second = cache.publish(b"second")
    with cache.acquire(first):
        pass
    third = cache.publish(b"third")
    with pytest.raises(AssetNotFound):
        cache.acquire(second)
    for mesh_id, data in [(first, b"first"), (third, b"third")]:
        with cache.acquire(mesh_id) as lease:
            assert lease.data == data


def test_byte_limit_can_evict_multiple_entries() -> None:
    cache = AssetCache(max_bytes=10, max_asset_bytes=10)
    first = cache.publish(b"111")
    second = cache.publish(b"222")
    third = cache.publish(b"333")
    fourth = cache.publish(b"4444444")
    for mesh_id in [first, second]:
        with pytest.raises(AssetNotFound):
            cache.acquire(mesh_id)
    with cache.acquire(third) as lease:
        assert lease.data == b"333"
    with cache.acquire(fourth) as lease:
        assert lease.data == b"4444444"


@pytest.mark.parametrize("config", [{"max_asset_bytes": 4}, {"max_bytes": 4}])
def test_oversized_asset_does_not_evict_existing_value(config: dict[str, int]) -> None:
    cache = AssetCache(**config)
    mesh_id = cache.publish(b"keep")
    with pytest.raises(AssetCapacityError):
        cache.publish(b"large")
    with cache.acquire(mesh_id) as lease:
        assert lease.data == b"keep"


def test_failed_capacity_preflight_preserves_eligible_live_entries() -> None:
    cache = AssetCache(max_bytes=10, max_asset_bytes=10)
    pinned_id = cache.publish(b"123456")
    available_id = cache.publish(b"abcd")
    with cache.acquire(pinned_id):
        with pytest.raises(AssetCapacityError):
            cache.publish(b"12345")
        with cache.acquire(available_id) as lease:
            assert lease.data == b"abcd"


def test_pins_count_toward_entry_limit_and_last_close_releases_them() -> None:
    cache = AssetCache(max_entries=1)
    mesh_id = cache.publish(b"old")
    first = cache.acquire(mesh_id)
    second = cache.acquire(mesh_id)
    first.close()
    first.close()
    with pytest.raises(AssetCapacityError):
        cache.publish(b"new")
    assert second.data == b"old"
    second.close()
    replacement = cache.publish(b"new")
    with cache.acquire(replacement) as lease:
        assert lease.data == b"new"


def test_expired_pinned_asset_remains_budgeted_until_read_finishes() -> None:
    clock = Clock()
    cache = AssetCache(max_bytes=3, max_asset_bytes=3, ttl_seconds=10, clock=clock)
    mesh_id = cache.publish(b"old")
    lease = cache.acquire(mesh_id)
    clock.value = 10
    with pytest.raises(AssetNotFound):
        cache.acquire(mesh_id)
    with pytest.raises(AssetCapacityError):
        cache.publish(b"new")
    assert lease.data == b"old"
    lease.close()
    replacement = cache.publish(b"new")
    with cache.acquire(replacement) as fresh:
        assert fresh.data == b"new"


def test_expired_entries_are_reclaimed_before_live_lru_entries() -> None:
    clock = Clock()
    cache = AssetCache(max_entries=2, ttl_seconds=10, clock=clock)
    expired = cache.publish(b"expired")
    clock.value = 5
    live = cache.publish(b"live")
    with cache.acquire(expired):
        pass
    clock.value = 10
    fresh = cache.publish(b"fresh")
    for mesh_id in [live, fresh]:
        with cache.acquire(mesh_id):
            pass
    with pytest.raises(AssetNotFound):
        cache.acquire(expired)


def test_lease_context_closes_on_exception() -> None:
    cache = AssetCache(max_entries=1)
    mesh_id = cache.publish(b"glb")
    with pytest.raises(RuntimeError, match="reader failure"):
        with cache.acquire(mesh_id) as lease:
            assert lease.data == b"glb"
            raise RuntimeError("reader failure")
    cache.publish(b"replacement")
    lease.close()
    with pytest.raises(RuntimeError, match="closed"):
        _ = lease.data


def test_close_allows_existing_read_to_finish_and_blocks_new_operations() -> None:
    cache = AssetCache()
    mesh_id = cache.publish(b"glb")
    lease = cache.acquire(mesh_id)
    cache.close()
    cache.close()
    assert lease.data == b"glb"
    with pytest.raises(AssetCacheClosed):
        cache.acquire(mesh_id)
    with pytest.raises(AssetCacheClosed):
        cache.publish(b"new")
    lease.close()
    lease.close()


def test_concurrent_read_pin_survives_expiry_and_competing_publication() -> None:
    clock = Clock()
    cache = AssetCache(max_entries=1, ttl_seconds=10, clock=clock)
    mesh_id = cache.publish(b"pinned")
    acquired = Event()
    finish = Event()

    def reader() -> bytes:
        with cache.acquire(mesh_id) as lease:
            acquired.set()
            assert finish.wait(5)
            return lease.data

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(reader)
        try:
            assert acquired.wait(5)
            clock.value = 10
            with pytest.raises(AssetCapacityError):
                cache.publish(b"new")
            with pytest.raises(AssetNotFound):
                cache.acquire(mesh_id)
        finally:
            finish.set()
        assert pending.result(timeout=5) == b"pinned"
    cache.publish(b"new")


def test_parallel_publish_respects_one_entry_budget_with_pinned_winner() -> None:
    cache = AssetCache(max_entries=1)
    start = Barrier(9)
    published = Event()
    finish = Event()

    def writer(index: int) -> str:
        start.wait(timeout=5)
        try:
            mesh_id = cache.publish(str(index).encode())
            # Another publication may evict an unpinned winner before acquire.
            try:
                lease = cache.acquire(mesh_id)
            except AssetNotFound:
                return "evicted"
            with lease:
                published.set()
                assert finish.wait(5)
                assert lease.data == str(index).encode()
                return "pinned"
        except AssetCapacityError:
            return "capacity"

    with ThreadPoolExecutor(max_workers=8) as pool:
        pending = [pool.submit(writer, index) for index in range(8)]
        start.wait(timeout=5)
        try:
            assert published.wait(5)
            with pytest.raises(AssetCapacityError):
                cache.publish(b"competing")
        finally:
            finish.set()
        outcomes = [result.result(timeout=5) for result in pending]
    assert "pinned" in outcomes


def test_close_publish_race_never_reopens_cache_or_invalidates_a_lease() -> None:
    cache = AssetCache()
    original = cache.publish(b"original")
    lease = cache.acquire(original)
    start = Barrier(3)

    def publish() -> str | None:
        start.wait(timeout=5)
        try:
            return cache.publish(b"race")
        except AssetCacheClosed:
            return None

    def close() -> None:
        start.wait(timeout=5)
        cache.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        publishing = pool.submit(publish)
        closing = pool.submit(close)
        start.wait(timeout=5)
        race_id = publishing.result(timeout=5)
        closing.result(timeout=5)
    assert lease.data == b"original"
    for mesh_id in [original, race_id or "0" * 32]:
        with pytest.raises(AssetCacheClosed):
            cache.acquire(mesh_id)
    with pytest.raises(AssetCacheClosed):
        cache.publish(b"later")
    lease.close()

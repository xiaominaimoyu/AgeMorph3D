"""Bounded process-local storage for immutable generated GLB bytes.

TTL starts at publication and never extends on access. A lease pins its entry
against eviction until the caller closes it. The cache owns no paths or files.
"""

import re
import secrets
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite
from numbers import Real
from threading import Lock


class AssetNotFound(Exception):
    """The requested identifier is invalid, absent, or expired."""


class AssetCapacityError(Exception):
    """An asset exceeds a limit or the remaining budget is pinned."""


class AssetCacheClosed(Exception):
    """The process-local cache has stopped accepting operations."""


@dataclass
class _Entry:
    data: bytes
    expires_at: float
    pins: int = 0


class AssetLease:
    """A pinned immutable value; close it when its response has finished."""

    def __init__(self, data: bytes, release: Callable[[], None]) -> None:
        self._data: bytes | None = data
        self._release: Callable[[], None] | None = release
        self._lock = Lock()

    @property
    def data(self) -> bytes:
        with self._lock:
            if self._data is None:
                raise RuntimeError("Asset lease is closed.")
            return self._data

    def close(self) -> None:
        with self._lock:
            release = self._release
            self._release = None
            self._data = None
        if release is not None:
            release()

    def __enter__(self) -> "AssetLease":
        # A closed lease must not silently enter another read scope.
        _ = self.data
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class AssetCache:
    """A thread-safe TTL/LRU cache whose budgets include pinned entries."""

    _ID = re.compile(r"[0-9a-f]{32}", re.ASCII)

    def __init__(
        self,
        max_bytes: int = 512 * 1024**2,
        ttl_seconds: float = 1800,
        max_entries: int = 128,
        max_asset_bytes: int = 64 * 1024**2,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        for name, value in (
            ("max_bytes", max_bytes),
            ("max_entries", max_entries),
            ("max_asset_bytes", max_asset_bytes),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer.")
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, Real)
            or not isfinite(ttl_seconds)
            or ttl_seconds <= 0
        ):
            raise ValueError("ttl_seconds must be positive and finite.")
        if not callable(clock):
            raise ValueError("clock must be callable.")
        self._max_bytes = max_bytes
        self._ttl_seconds = float(ttl_seconds)
        self._max_entries = max_entries
        self._max_asset_bytes = max_asset_bytes
        self._clock = clock
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._retained_bytes = 0
        self._closed = False
        self._lock = Lock()

    def _now(self) -> float:
        value = self._clock()
        if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
            raise ValueError("clock must return a finite number.")
        return float(value)

    def _require_open(self) -> None:
        if self._closed:
            raise AssetCacheClosed("Asset cache is closed.")

    def _remove(self, mesh_id: str) -> None:
        self._retained_bytes -= len(self._entries.pop(mesh_id).data)

    def _purge_expired(self, now: float) -> None:
        for mesh_id, entry in list(self._entries.items()):
            if entry.pins == 0 and entry.expires_at <= now:
                self._remove(mesh_id)

    def publish(self, data: bytes) -> str:
        """Publish one value atomically, evicting unpinned LRU entries as needed."""
        if type(data) is not bytes:
            raise TypeError("Asset data must be immutable bytes.")
        if not data:
            raise ValueError("Asset data must not be empty.")
        with self._lock:
            self._require_open()
            if len(data) > min(self._max_asset_bytes, self._max_bytes):
                raise AssetCapacityError("Asset exceeds the cache size limit.")
            now = self._now()
            expires_at = now + self._ttl_seconds
            if not isfinite(expires_at):
                raise ValueError("Asset expiration must be finite.")
            self._purge_expired(now)
            projected_bytes = self._retained_bytes + len(data)
            projected_count = len(self._entries) + 1
            victims: list[str] = []
            for mesh_id, entry in self._entries.items():
                if projected_bytes <= self._max_bytes and projected_count <= self._max_entries:
                    break
                if entry.pins == 0:
                    victims.append(mesh_id)
                    projected_bytes -= len(entry.data)
                    projected_count -= 1
            if projected_bytes > self._max_bytes or projected_count > self._max_entries:
                # Do not partially evict live entries when the request cannot fit.
                raise AssetCapacityError("Asset cache is busy; retry after active reads finish.")
            mesh_id = secrets.token_hex(16)
            while mesh_id in self._entries:
                mesh_id = secrets.token_hex(16)
            for victim in victims:
                self._remove(victim)
            self._entries[mesh_id] = _Entry(data, expires_at)
            self._retained_bytes += len(data)
            return mesh_id

    def acquire(self, mesh_id: str) -> AssetLease:
        """Pin a current value without extending its publication deadline."""
        with self._lock:
            self._require_open()
            if not isinstance(mesh_id, str) or self._ID.fullmatch(mesh_id) is None:
                raise AssetNotFound("Asset not found.")
            now = self._now()
            self._purge_expired(now)
            entry = self._entries.get(mesh_id)
            if entry is None or entry.expires_at <= now:
                raise AssetNotFound("Asset not found.")
            entry.pins += 1
            self._entries.move_to_end(mesh_id)
            return AssetLease(entry.data, lambda: self._release(mesh_id, entry))

    def _release(self, mesh_id: str, entry: _Entry) -> None:
        with self._lock:
            entry.pins -= 1
            if self._closed:
                return
            if entry.pins == 0 and entry.expires_at <= self._now():
                self._remove(mesh_id)

    def close(self) -> None:
        """Drop cache ownership; active leases can finish with their own bytes."""
        with self._lock:
            self._closed = True
            self._entries.clear()
            self._retained_bytes = 0

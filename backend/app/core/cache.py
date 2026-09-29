"""Thread-safe TTL + LRU cache for expensive responses.

Volume extractions and WMS tiles are pure functions of their query
parameters, so caching them turns a repeated time-animation loop from N
Zarr reads into one.  Kept in-process deliberately: no Redis to install for
a laptop demo, but the interface matches what a Redis backend would expose.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, TypeVar

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class TTLCache:
    """Bounded cache with per-entry expiry and least-recently-used eviction."""

    def __init__(self, *, max_entries: int = 128, ttl_seconds: int = 900, enabled: bool = True) -> None:
        self.max_entries = max(1, max_entries)
        self.ttl_seconds = max(1, ttl_seconds)
        self.enabled = enabled
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def _evict_expired_locked(self, now: float) -> None:
        expired = [key for key, (expiry, _) in self._store.items() if expiry <= now]
        for key in expired:
            self._store.pop(key, None)

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            expiry, value = entry
            if expiry <= now:
                self._store.pop(key, None)
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        with self._lock:
            self._evict_expired_locked(now)
            self._store[key] = (now + self.ttl_seconds, value)
            self._store.move_to_end(key)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)

    def get_or_set(self, key: str, factory: Callable[[], T]) -> T:
        """Return the cached value or compute, store and return it.

        The factory runs outside the lock so a slow extraction never blocks
        readers of unrelated keys.
        """
        cached = self.get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        value = factory()
        self.set(key, value)
        return value

    def clear(self) -> int:
        with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "enabled": self.enabled,
                "entries": len(self._store),
                "max_entries": self.max_entries,
                "ttl_seconds": self.ttl_seconds,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 4) if total else 0.0,
            }


def cache_key(prefix: str, **parts: Any) -> str:
    """Build a stable cache key from keyword parameters."""
    payload = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}:{digest}"

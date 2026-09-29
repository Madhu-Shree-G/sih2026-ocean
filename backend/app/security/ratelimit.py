"""In-process token-bucket rate limiting with progressive cool-down.

Two buckets are tracked per client: a general bucket for cheap metadata
routes and a stricter bucket for compute-heavy routes (volume extraction,
WMS rendering, drift simulation).  Clients that keep hitting the limit are
placed in a temporary cool-down so a hot loop cannot monopolise a worker.

The implementation is intentionally dependency-free and thread-safe.  For a
multi-process deployment behind a load balancer this should be backed by
Redis; the interface below is designed so that swap is a drop-in.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Literal

BucketKind = Literal["default", "heavy"]


@dataclass
class _Bucket:
    tokens: float
    capacity: float
    refill_per_second: float
    updated_at: float

    def consume(self, now: float, amount: float = 1.0) -> tuple[bool, float]:
        """Attempt to take ``amount`` tokens.

        Returns ``(allowed, retry_after_seconds)``.
        """
        elapsed = max(0.0, now - self.updated_at)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_second)
        self.updated_at = now

        if self.tokens >= amount:
            self.tokens -= amount
            return True, 0.0

        deficit = amount - self.tokens
        retry_after = deficit / self.refill_per_second if self.refill_per_second > 0 else 60.0
        return False, retry_after


@dataclass
class _ClientState:
    buckets: dict[str, _Bucket] = field(default_factory=dict)
    violations: int = 0
    blocked_until: float = 0.0
    last_seen: float = field(default_factory=time.monotonic)


@dataclass
class RateLimitDecision:
    allowed: bool
    retry_after: float = 0.0
    limit: int = 0
    remaining: int = 0
    reason: str = ""


class RateLimiter:
    """Token-bucket limiter keyed by client identity."""

    #: Clients idle for longer than this are evicted during sweeps.
    IDLE_EVICTION_SECONDS = 900
    #: Hard ceiling on tracked clients, so the limiter cannot itself be a leak.
    MAX_TRACKED_CLIENTS = 20_000

    def __init__(
        self,
        *,
        default_per_minute: int,
        heavy_per_minute: int,
        burst_multiplier: float = 1.5,
        block_seconds: int = 30,
        max_violations: int = 12,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self.block_seconds = block_seconds
        self.max_violations = max_violations
        self._limits: dict[str, int] = {
            "default": max(1, default_per_minute),
            "heavy": max(1, heavy_per_minute),
        }
        self._burst = max(1.0, burst_multiplier)
        self._clients: dict[str, _ClientState] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    # -- internals ---------------------------------------------------------
    def _new_bucket(self, kind: str, now: float) -> _Bucket:
        per_minute = self._limits[kind]
        capacity = per_minute * self._burst
        return _Bucket(
            tokens=capacity,
            capacity=capacity,
            refill_per_second=per_minute / 60.0,
            updated_at=now,
        )

    def _sweep_locked(self, now: float) -> None:
        if now - self._last_sweep < 60.0 and len(self._clients) < self.MAX_TRACKED_CLIENTS:
            return
        self._last_sweep = now
        stale = [
            key for key, state in self._clients.items()
            if now - state.last_seen > self.IDLE_EVICTION_SECONDS and now >= state.blocked_until
        ]
        for key in stale:
            self._clients.pop(key, None)

        # If still oversized, drop the least recently seen clients.
        if len(self._clients) > self.MAX_TRACKED_CLIENTS:
            ordered = sorted(self._clients.items(), key=lambda kv: kv[1].last_seen)
            for key, _ in ordered[: len(self._clients) - self.MAX_TRACKED_CLIENTS]:
                self._clients.pop(key, None)

    # -- public API --------------------------------------------------------
    def check(self, client_key: str, kind: BucketKind = "default") -> RateLimitDecision:
        if not self.enabled:
            return RateLimitDecision(allowed=True, limit=self._limits[kind], remaining=self._limits[kind])

        now = time.monotonic()
        with self._lock:
            self._sweep_locked(now)

            state = self._clients.get(client_key)
            if state is None:
                state = _ClientState()
                self._clients[client_key] = state
            state.last_seen = now

            if now < state.blocked_until:
                return RateLimitDecision(
                    allowed=False,
                    retry_after=round(state.blocked_until - now, 2),
                    limit=self._limits[kind],
                    remaining=0,
                    reason="cooldown",
                )

            bucket = state.buckets.get(kind)
            if bucket is None:
                bucket = self._new_bucket(kind, now)
                state.buckets[kind] = bucket

            allowed, retry_after = bucket.consume(now)
            if allowed:
                # Reward sustained good behaviour by decaying the violation count.
                if state.violations:
                    state.violations = max(0, state.violations - 1)
                return RateLimitDecision(
                    allowed=True,
                    limit=self._limits[kind],
                    # The bucket holds a burst allowance above the per-minute
                    # limit, but a client reading the headers should never see
                    # "remaining" exceed "limit".
                    remaining=min(int(bucket.tokens), self._limits[kind]),
                )

            state.violations += 1
            if state.violations >= self.max_violations:
                state.blocked_until = now + self.block_seconds
                state.violations = 0
                retry_after = float(self.block_seconds)

            return RateLimitDecision(
                allowed=False,
                retry_after=round(retry_after, 2),
                limit=self._limits[kind],
                remaining=0,
                reason="rate_limited",
            )

    def reset(self, client_key: str | None = None) -> None:
        """Clear limiter state - used by tests and by the admin endpoint."""
        with self._lock:
            if client_key is None:
                self._clients.clear()
            else:
                self._clients.pop(client_key, None)

    def stats(self) -> dict[str, int]:
        with self._lock:
            now = time.monotonic()
            return {
                "tracked_clients": len(self._clients),
                "blocked_clients": sum(1 for s in self._clients.values() if now < s.blocked_until),
            }

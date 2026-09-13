"""Per-token rate limiting.

The endpoint is reachable from the internet whenever Home Assistant is, and a
model in a retry loop can issue requests far faster than a person would. A
sliding window keeps one misbehaving client from saturating the instance
without penalising normal bursts the way a fixed window does.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock


class RateLimiter:
    """Sliding-window limiter keyed by an opaque caller identifier."""

    def __init__(self, max_calls: int, window_seconds: float) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")

        self._max_calls = max_calls
        self._window = window_seconds
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> float | None:
        """Record a call. Returns seconds to wait if the caller is over budget."""
        now = time.monotonic()
        with self._lock:
            calls = self._calls[key]
            cutoff = now - self._window
            while calls and calls[0] <= cutoff:
                calls.popleft()

            if len(calls) >= self._max_calls:
                # Budget frees up when the oldest call leaves the window.
                return round(calls[0] + self._window - now, 1)

            calls.append(now)
            return None

    def forget(self, key: str) -> None:
        with self._lock:
            self._calls.pop(key, None)

    def prune(self) -> None:
        """Drop callers with no recent activity so the map cannot grow forever."""
        cutoff = time.monotonic() - self._window
        with self._lock:
            for key in [k for k, v in self._calls.items() if not v or v[-1] <= cutoff]:
                del self._calls[key]


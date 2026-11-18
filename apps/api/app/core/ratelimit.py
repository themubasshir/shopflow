"""In-process sliding-window rate limiter (Phase 2B).

Used for the login endpoint: a single-shop POS runs one API process, so a
process-local counter is sufficient and avoids an external service. Not
intended as a general-purpose limiter — just enough to blunt credential
stuffing on the staff login.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict


class SlidingWindowLimiter:
    """Allow at most ``max_attempts`` events per ``window_seconds`` per key."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> list[float]:
        cutoff = now - self._window
        hits = [t for t in self._hits[key] if t > cutoff]
        self._hits[key] = hits
        return hits

    def check(self, key: str) -> int:
        """Return how many attempts remain before the limit is hit (0 == blocked)."""
        with self._lock:
            remaining = self._max - len(self._prune(key, time.monotonic()))
        return max(0, remaining)

    def hit(self, key: str) -> None:
        """Record one attempt against ``key``."""
        with self._lock:
            now = time.monotonic()
            self._prune(key, now)
            self._hits[key].append(now)

    def reset(self, key: str) -> None:
        """Clear a key — e.g. after a successful login."""
        with self._lock:
            self._hits.pop(key, None)

    def retry_after(self, key: str) -> int:
        """Seconds until the oldest recorded attempt leaves the window."""
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 0
            wait = self._window - (time.monotonic() - hits[0])
        return max(1, int(wait))

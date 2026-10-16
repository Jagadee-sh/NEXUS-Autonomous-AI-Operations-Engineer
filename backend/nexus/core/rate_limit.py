"""In-process sliding-window rate limiter."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from nexus.config import settings


class RateLimiter:
    def __init__(self, limit_per_minute: int | None = None):
        self.limit = limit_per_minute or settings.rate_limit_per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > 60.0:
                q.popleft()
            if len(q) >= self.limit:
                return False, int(60 - (now - q[0])) + 1
            q.append(now)
            return True, 0


limiter = RateLimiter()

"""Per-client sliding-window rate limiting.

Keyed by client IP (first hop of
X-Forwarded-For, which Cloud Run sets). Limits are per instance. For a hard global
limit, put Cloud Armor or API Gateway in front (see docs/production-readiness.md).
"""

from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, clock=time.monotonic) -> None:
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = self.clock()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False, max(1, int(self.window - (now - q[0])) + 1)
            q.append(now)
            if len(self._hits) > 50_000:  # crude memory guard
                self._hits = {k: v for k, v in self._hits.items() if v}
            return True, 0

"""Minimal in-memory sliding-window rate limiter (single-process deployment)."""

from __future__ import annotations

import hashlib
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = {}

    @staticmethod
    def key_for(ip: str) -> str:
        return hashlib.sha256(ip.encode()).hexdigest()[:16]  # never keep raw IPs

    def allow(self, ip: str) -> tuple[bool, int]:
        if self.per_minute <= 0:
            return True, 0
        now = time.monotonic()
        q = self._hits.setdefault(self.key_for(ip), deque())
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            return False, int(60 - (now - q[0])) + 1
        q.append(now)
        if len(self._hits) > 10000:
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < 60}
        return True, 0

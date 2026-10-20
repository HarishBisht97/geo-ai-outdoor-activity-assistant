"""In-memory TTL cache with in-flight request coalescing.

Concurrent callers asking for the same key share one upstream call instead of issuing
duplicates. Failures are never cached.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from cachetools import TTLCache

T = TypeVar("T")


class AsyncTTLCache:
    def __init__(self, maxsize: int = 2048):
        self._caches: dict[int, TTLCache] = {}
        self._maxsize = maxsize
        self._inflight: dict[str, asyncio.Future] = {}
        self.hits = 0
        self.misses = 0

    def _bucket(self, ttl: int) -> TTLCache:
        if ttl not in self._caches:
            self._caches[ttl] = TTLCache(maxsize=self._maxsize, ttl=ttl)
        return self._caches[ttl]

    def peek(self, key: str, ttl: int) -> Any | None:
        return self._bucket(ttl).get(key)

    def put(self, key: str, ttl: int, value: Any) -> None:
        self._bucket(ttl)[key] = value

    async def get_or_fetch(self, key: str, ttl: int, fetch: Callable[[], Awaitable[T]]) -> tuple[T, bool]:
        """Returns (value, cache_hit)."""
        bucket = self._bucket(ttl)
        if key in bucket:
            self.hits += 1
            return bucket[key], True
        if key in self._inflight:
            self.hits += 1
            return await asyncio.shield(self._inflight[key]), True
        self.misses += 1
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._inflight[key] = fut
        try:
            value = await fetch()
        except BaseException as exc:
            fut.set_exception(exc)
            fut.exception()  # mark retrieved so un-awaited futures don't warn
            raise
        else:
            bucket[key] = value
            fut.set_result(value)
            return value, False
        finally:
            self._inflight.pop(key, None)

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "entries": sum(len(c) for c in self._caches.values())}

    def clear(self) -> None:
        for c in self._caches.values():
            c.clear()

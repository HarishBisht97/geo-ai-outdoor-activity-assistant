"""Shared async HTTP client: per-host politeness limits, bounded retries with jittered backoff,
Retry-After support and mirror rotation. Adapters build on `fetch_json`."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from app.core.errors import ProviderError
from app.core.logging import log_event

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Minimum interval between requests to a host (seconds), per provider usage policies.
HOST_MIN_INTERVAL = {
    "nominatim.openstreetmap.org": 1.1,
    "router.project-osrm.org": 1.0,
    "routing.openstreetmap.de": 1.0,
    "overpass-api.de": 0.5,
}


class HostThrottle:
    def __init__(self, intervals: dict[str, float] | None = None) -> None:
        self._intervals = HOST_MIN_INTERVAL if intervals is None else intervals
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    async def wait(self, host: str) -> None:
        interval = self._intervals.get(host)
        if not interval:
            return
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            delay = self._last.get(host, 0) + interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last[host] = time.monotonic()


class HttpClient:
    def __init__(self, user_agent: str, timeout_s: float = 20, retries: int = 2, transport=None,
                 throttle: bool = True):
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=httpx.Timeout(timeout_s, connect=8),
            transport=transport,
            follow_redirects=True,
        )
        self.retries = retries
        self.throttle = HostThrottle(None if throttle else {})

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch_json(
        self,
        provider: str,
        urls: list[str] | str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        timeout_s: float | None = None,
        retries: int | None = None,
        deadline_s: float | None = None,
        retry_timeouts: bool = True,
    ) -> tuple[Any, str]:
        """GET (or POST form when `data` given). Tries each mirror in order with retries.

        `deadline_s` bounds the total time across all mirrors and attempts. With `retry_timeouts=False`
        a timed-out mirror is not retried (the next mirror is tried instead).
        Returns (parsed_json, url_used). Raises ProviderError when every attempt fails.
        """
        mirrors = [urls] if isinstance(urls, str) else list(urls)
        n_retries = self.retries if retries is None else retries
        end = time.monotonic() + deadline_s if deadline_s else None
        last_error = "no attempt made"
        last_status: int | None = None
        for base in mirrors:
            host = urlparse(base).netloc
            for attempt in range(n_retries + 1):
                attempt_timeout = timeout_s
                if end is not None:
                    remaining = end - time.monotonic()
                    if remaining < 1:
                        raise ProviderError(provider, f"time budget exhausted ({last_error})", last_status)
                    attempt_timeout = min(timeout_s or remaining, remaining)
                await self.throttle.wait(host)
                try:
                    if data is not None:
                        resp = await self._client.post(base, data=data, timeout=attempt_timeout)
                    else:
                        resp = await self._client.get(base, params=params, timeout=attempt_timeout)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_error, last_status = f"{type(exc).__name__}", None
                    log_event(logger, "http_retryable_error", logging.WARNING, provider=provider, host=host,
                              attempt=attempt, error=last_error)
                    if isinstance(exc, httpx.TimeoutException) and not retry_timeouts:
                        break
                    if attempt < n_retries:
                        await asyncio.sleep(_backoff(attempt))
                    continue
                if resp.status_code == 200:
                    try:
                        payload = resp.json()
                    except ValueError:
                        last_error, last_status = "invalid JSON body", 200
                        break
                    shown = base if data is not None else f"{base}?{urlencode(params or {}, safe=',:')}"
                    return payload, shown
                last_status = resp.status_code
                last_error = f"HTTP {resp.status_code}"
                log_event(logger, "http_bad_status", logging.WARNING, provider=provider, host=host,
                          attempt=attempt, status=resp.status_code)
                if resp.status_code not in RETRYABLE_STATUS:
                    break
                if attempt < n_retries:
                    await asyncio.sleep(_retry_after(resp) or _backoff(attempt))
        raise ProviderError(provider, last_error, last_status)


def _backoff(attempt: int) -> float:
    return min(8.0, 0.75 * (2**attempt)) + random.uniform(0, 0.4)


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return min(10.0, float(value))
    except ValueError:
        return None

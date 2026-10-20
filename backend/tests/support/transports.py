"""HTTP record / replay for fixture-based tests.

`RecordingTransport` wraps a real transport and captures every exchange (including timeouts and
transport errors). `ReplayTransport` serves the captured exchanges by request key, and applies optional
`Override`s so failure modes (503s, null air quality, thunderstorms, empty results) can be derived from
real recorded sessions instead of hand-written payloads.

Fixtures are test-only: the runtime package must never import this module (see test_guard.py).
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import httpx

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sessions"

ERRORS: dict[str, type[Exception]] = {
    "ReadTimeout": httpx.ReadTimeout,
    "ConnectTimeout": httpx.ConnectTimeout,
    "ConnectError": httpx.ConnectError,
    "RemoteProtocolError": httpx.RemoteProtocolError,
}


def request_key(request: httpx.Request) -> str:
    params = sorted(request.url.params.multi_items())
    body: list = []
    if request.method == "POST" and request.content:
        body = sorted(parse_qsl(request.content.decode()))
    return json.dumps([request.method, f"{request.url.host}{request.url.path}", params, body])


@dataclass
class Exchange:
    key: str
    method: str
    url: str
    status: int | None = None
    body: Any = None  # parsed JSON, or text when not JSON
    is_json: bool = True
    error: str | None = None

    def response(self, request: httpx.Request) -> httpx.Response:
        if self.error:
            raise ERRORS.get(self.error, httpx.ConnectError)(f"recorded {self.error}", request=request)
        if self.is_json:
            return httpx.Response(self.status or 200, json=self.body, request=request)
        return httpx.Response(self.status or 200, text=self.body or "", request=request)


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner: httpx.AsyncBaseTransport | None = None):
        self.inner = inner or httpx.AsyncHTTPTransport()
        self.exchanges: list[Exchange] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        ex = Exchange(request_key(request), request.method, str(request.url))
        try:
            resp = await self.inner.handle_async_request(request)
        except httpx.HTTPError as exc:
            ex.error = type(exc).__name__
            self.exchanges.append(ex)
            raise
        content = await resp.aread()
        ex.status = resp.status_code
        try:
            ex.body = json.loads(content)
        except ValueError:
            ex.body, ex.is_json = content.decode(errors="replace")[:2000], False
        self.exchanges.append(ex)
        headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-encoding", "content-length",
                                                                               "transfer-encoding")}
        return httpx.Response(resp.status_code, headers=headers, content=content, request=request)

    async def aclose(self) -> None:
        await self.inner.aclose()


# --------------------------------------------------------------------------- overrides
@dataclass
class Override:
    """Applies to requests whose host contains `host` (and path contains `path`)."""

    host: str
    path: str = ""
    status: int | None = None
    error: str | None = None
    mutate: Callable[[Any, httpx.Request], Any] | None = None

    def matches(self, request: httpx.Request) -> bool:
        return self.host in request.url.host and self.path in request.url.path


def fail(host: str, status: int = 503, path: str = "") -> Override:
    return Override(host, path, status=status)


def timeout(host: str, path: str = "") -> Override:
    return Override(host, path, error="ReadTimeout")


def mutate(host: str, fn: Callable[[Any, httpx.Request], Any], path: str = "") -> Override:
    return Override(host, path, mutate=fn)


@dataclass
class Session:
    name: str
    question: str
    recorded_at: datetime
    request: dict
    exchanges: list[Exchange] = field(default_factory=list)

    @classmethod
    def load(cls, name: str) -> Session:
        path = FIXTURE_DIR / f"{name}.json.gz"
        with gzip.open(path, "rt", encoding="utf-8") as f:
            raw = json.load(f)
        return cls(raw["name"], raw["question"], datetime.fromisoformat(raw["recorded_at"]), raw["request"],
                   [Exchange(**e) for e in raw["exchanges"]])

    def save(self) -> Path:
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        path = FIXTURE_DIR / f"{self.name}.json.gz"
        data = {"name": self.name, "question": self.question, "recorded_at": self.recorded_at.isoformat(),
                "request": self.request, "exchanges": [e.__dict__ for e in self.exchanges]}
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        return path


class ReplayTransport(httpx.AsyncBaseTransport):
    """Serves recorded exchanges; unknown requests get a connection error (never the network)."""

    def __init__(self, exchanges: list[Exchange], overrides: list[Override] | None = None):
        self._by_key: dict[str, list[Exchange]] = {}
        for e in exchanges:
            self._by_key.setdefault(e.key, []).append(e)
        self._served: dict[str, int] = {}
        self.overrides = overrides or []
        self.missed: list[str] = []
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        ov = next((o for o in self.overrides if o.matches(request)), None)
        if ov and ov.error:
            raise ERRORS[ov.error]("injected", request=request)
        if ov and ov.status:
            return httpx.Response(ov.status, json={"error": "injected"}, request=request)
        key = request_key(request)
        options = self._by_key.get(key)
        if not options:
            self.missed.append(key)
            raise httpx.ConnectError(f"no recorded exchange for {request.url.host}{request.url.path}",
                                     request=request)
        i = self._served.get(key, 0)
        self._served[key] = i + 1
        ex = options[min(i, len(options) - 1)]
        if ov and ov.mutate and ex.error is None and ex.is_json:
            body = ov.mutate(json.loads(json.dumps(ex.body)), request)
            return httpx.Response(ex.status or 200, json=body, request=request)
        return ex.response(request)

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.cache.ttl_cache import AsyncTTLCache
from app.core import http as http_mod
from app.core.errors import ProviderError
from app.core.http import HttpClient
from app.services.base import ServiceDeps
from app.services.open_meteo import WEATHER_HOURLY, coord_key, fetch_forecasts
from app.services.routing import route_table
from tests.conftest import make_settings


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(http_mod, "_backoff", lambda attempt: 0.0)


def client(handler, retries=2):
    return HttpClient("test-agent", retries=retries, transport=httpx.MockTransport(handler), throttle=False)


def deps_for(handler, **settings):
    return ServiceDeps(make_settings(**settings), client(handler, retries=0), AsyncTTLCache())


# --------------------------------------------------------------------------- HTTP client
async def test_retries_retryable_status_then_succeeds():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"ok": True})

    data, url = await client(handler).fetch_json("p", "https://a.example/x", params={"q": "1"})
    assert data == {"ok": True} and len(calls) == 3
    assert url == "https://a.example/x?q=1"
    assert calls[0].headers["User-Agent"] == "test-agent"


async def test_non_retryable_status_moves_to_next_mirror():
    seen = []

    def handler(req):
        seen.append(req.url.host)
        return httpx.Response(400) if req.url.host == "a.example" else httpx.Response(200, json=[1])

    data, url = await client(handler).fetch_json("p", ["https://a.example/i", "https://b.example/i"])
    assert data == [1] and seen == ["a.example", "b.example"]
    assert url.startswith("https://b.example")


async def test_all_mirrors_fail_raises_provider_error_with_status():
    with pytest.raises(ProviderError) as e:
        await client(lambda r: httpx.Response(502), retries=1).fetch_json("p", ["https://a.example", "https://b.example"])
    assert e.value.status == 502 and "502" in e.value.message


async def test_invalid_json_is_an_error():
    with pytest.raises(ProviderError) as e:
        await client(lambda r: httpx.Response(200, content=b"<html>")).fetch_json("p", "https://a.example")
    assert "JSON" in e.value.message


async def test_timeout_without_retry_goes_to_next_mirror():
    seen = []

    def handler(req):
        seen.append(req.url.host)
        if req.url.host == "a.example":
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(200, json={})

    await client(handler).fetch_json("p", ["https://a.example", "https://b.example"], retry_timeouts=False)
    assert seen == ["a.example", "b.example"]


async def test_deadline_exhausted():
    with pytest.raises(ProviderError) as e:
        await client(lambda r: httpx.Response(503)).fetch_json("p", "https://a.example", deadline_s=0.5)
    assert "budget" in e.value.message


async def test_post_form():
    def handler(req):
        assert req.method == "POST" and b"data=" in req.content
        return httpx.Response(200, json={"elements": []})

    data, _ = await client(handler).fetch_json("p", "https://a.example/api", data={"data": "[out:json];"})
    assert data == {"elements": []}


# --------------------------------------------------------------------------- cache
async def test_cache_coalesces_concurrent_fetches_and_never_caches_failures():
    cache = AsyncTTLCache()
    calls = 0

    async def fetch():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return calls

    results = await asyncio.gather(*(cache.get_or_fetch("k", 60, fetch) for _ in range(5)))
    assert calls == 1 and [v for v, _ in results] == [1] * 5
    assert sum(hit for _, hit in results) == 4

    async def boom():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        await cache.get_or_fetch("bad", 60, boom)
    value, hit = await cache.get_or_fetch("bad", 60, fetch)
    assert value == 2 and hit is False


# --------------------------------------------------------------------------- Open-Meteo / OSRM parsing
def om_location(lat, lon, n=3, temp=None):
    t0 = 1792886400  # 2026-10-25T00:00Z
    hourly = {"time": [t0 + 3600 * i for i in range(n)]}
    for v in WEATHER_HOURLY:
        hourly[v] = [1.0] * n
    hourly["temperature_2m"] = temp or [20.0, None, None]
    return {"latitude": lat, "longitude": lon, "timezone": "Asia/Kolkata", "utc_offset_seconds": 19800,
            "elevation": 50.0, "hourly": hourly, "hourly_units": {"temperature_2m": "°C"},
            "daily": {"time": [t0 - 19800], "sunrise": [t0 + 3600], "sunset": [t0 + 40000]}}


async def test_forecast_batches_distinct_cells_and_parses():
    requests = []

    def handler(req):
        requests.append(req)
        lats = req.url.params["latitude"].split(",")
        lons = req.url.params["longitude"].split(",")
        return httpx.Response(200, json=[om_location(float(a), float(b)) for a, b in zip(lats, lons, strict=True)])

    deps = deps_for(handler)
    coords = [(19.1176, 72.906), (19.118, 72.907), (19.20, 72.95)]  # first two share a 0.02 deg cell
    got = await fetch_forecasts(deps, coords)
    assert got.ok and got.provenance.status == "ok"
    assert len(requests) == 1 and len(requests[0].url.params["latitude"].split(",")) == 2
    loc = got.data[coord_key(19.1176, 72.906)]
    assert loc.timezone == "Asia/Kolkata" and loc.elevation_m == 50.0
    assert loc.coverage_end("temperature_2m") == loc.times[0]
    assert loc.series["temperature_2m"][1] is None
    assert loc.sun[0][1] is not None
    again = await fetch_forecasts(deps, coords)
    assert again.provenance.cache_hit and len(requests) == 1


async def test_forecast_failure_is_reported_not_raised():
    got = await fetch_forecasts(deps_for(lambda r: httpx.Response(500)), [(19.1, 72.9)])
    assert not got.ok and got.provenance.status == "failed" and got.provenance.error


async def test_osrm_table_parsing_and_partial():
    def handler(req):
        assert "/table/v1/driving/" in req.url.path and req.url.params["sources"] == "0"
        return httpx.Response(200, json={"code": "Ok", "durations": [[0, 600.0, None]],
                                         "distances": [[0, 4000.0, None]]})

    got = await route_table(deps_for(handler), (19.1, 72.9), [(19.12, 72.91), (19.2, 72.95)], "driving")
    assert got.data[0].duration_s == 600 and got.data[1].duration_s is None
    assert got.provenance.status == "partial"
    assert "no live traffic" in " ".join(got.provenance.limitations)

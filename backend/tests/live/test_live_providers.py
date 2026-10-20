"""Opt-in smoke tests against the real free APIs: `pytest -m live`. Not run in CI by default."""

from __future__ import annotations

import pytest

from app.cache.ttl_cache import AsyncTTLCache
from app.core.config import Settings
from app.core.http import HttpClient
from app.services.base import ServiceDeps
from app.services.geocoding import geocode
from app.services.open_meteo import fetch_air_quality, fetch_forecasts
from app.services.routing import route_table

pytestmark = pytest.mark.live


@pytest.fixture
async def deps():
    s = Settings()
    http = HttpClient(s.user_agent, timeout_s=20, retries=1)
    yield ServiceDeps(s, http, AsyncTTLCache())
    await http.aclose()


async def test_nominatim(deps):
    got = await geocode(deps, "Powai, Mumbai")
    assert got.ok and any(abs(r.lat - 19.12) < 0.1 for r in got.data)


async def test_open_meteo(deps):
    w = await fetch_forecasts(deps, [(19.12, 72.91)])
    a = await fetch_air_quality(deps, [(19.12, 72.91)])
    assert w.ok and a.ok
    loc = next(iter(w.data.values()))
    assert loc.timezone == "Asia/Kolkata" and len(loc.times) >= 48


async def test_osrm(deps):
    got = await route_table(deps, (19.1176, 72.906), [(19.13, 72.91)], "driving")
    assert got.ok and got.data[0].duration_s

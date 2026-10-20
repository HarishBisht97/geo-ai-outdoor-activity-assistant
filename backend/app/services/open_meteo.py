"""Open-Meteo adapters: hourly forecast (+ daily sunrise/sunset), air quality, elevation.

Free tier: non-commercial use, < 10,000 calls/day, 5,000/hour, 600/minute; data CC BY 4.0.
All multi-location requests are batched (comma-separated coordinates). Times are requested as unix
timestamps so they are unambiguous; the IANA timezone comes from `timezone=auto`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core.errors import ProviderError
from app.services.base import OPEN_METEO_ATTRIBUTION, Fetched, ServiceDeps, make_provenance, round_coord

WEATHER_HOURLY = [
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "precipitation_probability",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "cloud_cover_low",
    "visibility",
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "uv_index",
    "is_day",
]
AIR_HOURLY = ["pm2_5", "pm10", "nitrogen_dioxide", "ozone", "us_aqi"]


@dataclass
class LocationSeries:
    key: str
    grid_lat: float
    grid_lon: float
    timezone: str
    utc_offset_seconds: int
    times: list[datetime]
    series: dict[str, list[float | None]]
    units: dict[str, str]
    elevation_m: float | None = None
    sun: list[tuple[str, datetime | None, datetime | None]] = field(default_factory=list)

    def coverage_end(self, var: str) -> datetime | None:
        """Last timestamp with a non-null value for `var`."""
        vals = self.series.get(var) or []
        for t, v in zip(reversed(self.times), reversed(vals), strict=False):
            if v is not None:
                return t
        return None


def coord_key(lat: float, lon: float, step: float = 0.02) -> str:
    return f"{round_coord(lat, step)},{round_coord(lon, step)}"


def _ts(v) -> datetime | None:
    if v is None:
        return None
    return datetime.fromtimestamp(int(v), tz=UTC)


def _parse_location(key: str, obj: dict, hourly_vars: list[str]) -> LocationSeries:
    hourly = obj.get("hourly") or {}
    times = [_ts(t) for t in hourly.get("time", [])]
    series = {v: list(hourly.get(v, [None] * len(times))) for v in hourly_vars}
    sun = []
    daily = obj.get("daily") or {}
    if daily.get("time"):
        offset = int(obj.get("utc_offset_seconds") or 0)
        for i, d in enumerate(daily["time"]):
            day = datetime.fromtimestamp(int(d) + offset, tz=UTC).date().isoformat()
            sr = (daily.get("sunrise") or [None] * len(daily["time"]))[i]
            ss = (daily.get("sunset") or [None] * len(daily["time"]))[i]
            sun.append((day, _ts(sr), _ts(ss)))
    return LocationSeries(
        key=key,
        grid_lat=float(obj.get("latitude")),
        grid_lon=float(obj.get("longitude")),
        timezone=obj.get("timezone") or "UTC",
        utc_offset_seconds=int(obj.get("utc_offset_seconds") or 0),
        times=times,
        series=series,
        units=obj.get("hourly_units") or {},
        elevation_m=obj.get("elevation"),
        sun=sun,
    )


async def _batched(
    deps: ServiceDeps,
    *,
    provider: str,
    pid: str,
    url: str,
    coords: list[tuple[float, float]],
    base_params: dict,
    hourly_vars: list[str],
    ttl: int,
    kind: str,
    limitations: list[str],
    step: float,
) -> Fetched[dict[str, LocationSeries]]:
    """Fetch each distinct rounded coordinate once; serve the rest from cache."""
    keys: dict[str, tuple[float, float]] = {}
    for lat, lon in coords:
        keys.setdefault(coord_key(lat, lon, step), (round_coord(lat, step), round_coord(lon, step)))
    result: dict[str, LocationSeries] = {}
    missing = []
    for k in keys:
        cached = deps.cache.peek(f"{pid}:{k}", ttl)
        if cached is not None:
            result[k] = cached
        else:
            missing.append(k)
    used_url = url
    hit = not missing
    if missing:
        params = dict(base_params)
        params["latitude"] = ",".join(str(keys[k][0]) for k in missing)
        params["longitude"] = ",".join(str(keys[k][1]) for k in missing)
        batch_key = f"{pid}:batch:" + "|".join(missing)

        async def fetch():
            return await deps.http.fetch_json(provider, url, params=params)

        try:
            (payload, used_url), _ = await deps.cache.get_or_fetch(batch_key, ttl, fetch)
        except ProviderError as exc:
            status = "partial" if result else "failed"
            return Fetched(
                result or None,
                make_provenance(pid, provider, url=url, kind=kind, license="CC BY 4.0",
                                attribution=OPEN_METEO_ATTRIBUTION, status=status, error=exc.message,
                                limitations=limitations),
            )
        objs = payload if isinstance(payload, list) else [payload]
        for k, obj in zip(missing, objs, strict=False):
            if not isinstance(obj, dict) or obj.get("error"):
                continue
            loc = _parse_location(k, obj, hourly_vars)
            deps.cache.put(f"{pid}:{k}", ttl, loc)
            result[k] = loc
    status = "ok" if len(result) == len(keys) else ("partial" if result else "failed")
    return Fetched(
        result or None,
        make_provenance(pid, provider, url=used_url, kind=kind, license="CC BY 4.0",
                        attribution=OPEN_METEO_ATTRIBUTION, cache_hit=hit, status=status,
                        limitations=limitations),
    )


async def fetch_forecasts(deps: ServiceDeps, coords: list[tuple[float, float]]) -> Fetched[dict[str, LocationSeries]]:
    s = deps.settings
    return await _batched(
        deps,
        provider="Open-Meteo Forecast API",
        pid="weather:open-meteo",
        url=s.open_meteo_url,
        coords=coords,
        base_params={
            "hourly": ",".join(WEATHER_HOURLY),
            "daily": "sunrise,sunset",
            "timezone": "auto",
            "timeformat": "unixtime",
            "forecast_days": s.max_window_days + 1,
            "past_days": 1,
            "wind_speed_unit": "kmh",
        },
        hourly_vars=WEATHER_HOURLY,
        ttl=s.cache_ttl_weather,
        kind="forecast",
        limitations=[
            "Numerical weather model forecast (best-match model blend), not an observation.",
            "Grid resolution ~1-11 km depending on model; venues in the same cell share values.",
            "Forecast model run time is not exposed; retrieval time is recorded instead.",
        ],
        step=0.02,
    )


async def fetch_air_quality(deps: ServiceDeps, coords: list[tuple[float, float]]) -> Fetched[dict[str, LocationSeries]]:
    s = deps.settings
    return await _batched(
        deps,
        provider="Open-Meteo Air Quality API (CAMS)",
        pid="air:open-meteo",
        url=s.open_meteo_aq_url,
        coords=coords,
        base_params={
            "hourly": ",".join(AIR_HOURLY),
            "timezone": "auto",
            "timeformat": "unixtime",
            "forecast_days": 7,
            "past_days": 1,
        },
        hourly_vars=AIR_HOURLY,
        ttl=s.cache_ttl_air,
        kind="modeled",
        limitations=[
            "CAMS atmospheric-composition model output, not a station measurement.",
            "Coarse resolution outside Europe (~0.4 deg, ~45 km): does not resolve street-level variation.",
            "US AQI is the US EPA scale computed by Open-Meteo; it is not India's National AQI.",
            "Forecast coverage is ~5 days; later hours are reported as unavailable.",
        ],
        step=0.1,
    )


async def fetch_elevations(deps: ServiceDeps, coords: list[tuple[float, float]]) -> Fetched[list[float | None]]:
    s = deps.settings
    if not coords:
        return Fetched([], make_provenance("elevation:open-meteo", "Open-Meteo Elevation API", url=None,
                                           kind="observed", license="CC BY 4.0",
                                           attribution=OPEN_METEO_ATTRIBUTION, status="skipped"))
    coords = coords[:100]
    params = {
        "latitude": ",".join(f"{lat:.5f}" for lat, _ in coords),
        "longitude": ",".join(f"{lon:.5f}" for _, lon in coords),
    }
    key = "elev:" + params["latitude"] + ";" + params["longitude"]

    async def fetch():
        return await deps.http.fetch_json("open-meteo-elevation", s.open_meteo_elevation_url, params=params)

    try:
        (payload, used), hit = await deps.cache.get_or_fetch(key, s.cache_ttl_elevation, fetch)
    except ProviderError as exc:
        return Fetched(None, make_provenance("elevation:open-meteo", "Open-Meteo Elevation API",
                                             url=s.open_meteo_elevation_url, kind="observed", license="CC BY 4.0",
                                             attribution=OPEN_METEO_ATTRIBUTION, status="failed",
                                             error=exc.message))
    elev = payload.get("elevation") or []
    return Fetched(
        [float(e) if e is not None else None for e in elev],
        make_provenance("elevation:open-meteo", "Open-Meteo Elevation API", url=used, kind="observed",
                        license="CC BY 4.0", attribution=OPEN_METEO_ATTRIBUTION, cache_hit=hit,
                        limitations=["Copernicus DEM GLO-90 (90 m) terrain elevation."]),
    )

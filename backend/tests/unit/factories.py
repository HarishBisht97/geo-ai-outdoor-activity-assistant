"""Synthetic evidence builders for engine unit tests (no network)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.ranking.conditions import SeriesIndex
from app.ranking.ranker import VenueEvidence
from app.ranking.scoring import TravelEvidence
from app.schemas.common import Coordinates
from app.schemas.venue import Venue
from app.services.open_meteo import AIR_HOURLY, WEATHER_HOURLY, LocationSeries

IST = ZoneInfo("Asia/Kolkata")
# Wed 21 Oct 2026 00:00 IST
T0 = datetime(2026, 10, 21, 0, 0, tzinfo=IST).astimezone(UTC)

BENIGN_WEATHER = {
    "temperature_2m": 22.0, "relative_humidity_2m": 50.0, "apparent_temperature": 22.0,
    "precipitation_probability": 0.0, "precipitation": 0.0, "weather_code": 1.0, "cloud_cover": 20.0,
    "cloud_cover_low": 10.0, "visibility": 20000.0, "wind_speed_10m": 8.0, "wind_direction_10m": 90.0,
    "wind_gusts_10m": 15.0, "uv_index": 2.0, "is_day": 1.0,
}
BENIGN_AIR = {"pm2_5": 8.0, "pm10": 15.0, "nitrogen_dioxide": 10.0, "ozone": 40.0, "us_aqi": 35.0}


def series(values: dict[str, float | None] | None = None, hours: int = 72, overrides: dict | None = None,
           air: bool = False) -> LocationSeries:
    """Constant series; `overrides` maps var -> {hour_index: value} or a callable(hour_index) -> value."""
    base = dict(BENIGN_AIR if air else BENIGN_WEATHER)
    base.update(values or {})
    times = [T0 + timedelta(hours=h) for h in range(hours)]
    data: dict[str, list[float | None]] = {}
    for var in AIR_HOURLY if air else WEATHER_HOURLY:
        col = [base.get(var)] * hours
        ov = (overrides or {}).get(var)
        if callable(ov):
            col = [ov(h) for h in range(hours)]
        elif isinstance(ov, dict):
            for h, v in ov.items():
                col[h] = v
        data[var] = col
    day = T0.astimezone(IST).date()
    sun = [((day + timedelta(days=d)).isoformat(),
            datetime(2026, 10, 21 + d, 6, 34, tzinfo=IST), datetime(2026, 10, 21 + d, 18, 11, tzinfo=IST))
           for d in range(hours // 24 + 1)]
    return LocationSeries(key="k", grid_lat=19.12, grid_lon=72.9, timezone="Asia/Kolkata", utc_offset_seconds=19800,
                          times=times, series=data, units={}, sun=sun)


def venue(vid: str = "osm:way:1", name: str | None = "Test Park", category: str = "park", distance_km: float = 1.0,
          suitability: str = "explicit", tags: dict | None = None) -> Venue:
    n = int(vid.rsplit(":", 1)[-1])
    return Venue(id=vid, name=name, display_label=name or f"Unnamed park (OSM way {n})",
                 coords=Coordinates(lat=19.12, lon=72.90), osm_type="way", osm_id=n,
                 osm_url=f"https://www.openstreetmap.org/way/{n}", tags=tags or {}, category=category,
                 suitability=suitability, distance_km=distance_km, source_id="places:overpass")


def evidence(v: Venue | None = None, weather: LocationSeries | None = None, air: LocationSeries | None = None,
             travel_min: float | None = 10.0, mode: str = "walking") -> VenueEvidence:
    w = weather if weather is not None else series()
    a = air if air is not None else series(air=True)
    sun = {d: (sr, ss) for d, sr, ss in w.sun}
    v = v or venue()
    return VenueEvidence(v, SeriesIndex(w), SeriesIndex(a), sun,
                         TravelEvidence(mode=mode, duration_min=travel_min, route_km=None, straight_km=v.distance_km),
                         None, [])


def local(h: int, day: int = 21) -> datetime:
    return datetime(2026, 10, day, h, 0, tzinfo=IST)

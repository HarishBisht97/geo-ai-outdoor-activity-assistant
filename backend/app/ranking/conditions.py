"""Aggregate hourly forecast / air-quality series over a slot into SlotConditions (with provenance)."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.ranking.time_slots import Slot
from app.schemas.common import EvidenceValue
from app.schemas.responses import HourPoint, SlotConditions
from app.services.open_meteo import LocationSeries
from app.utils.units import heat_index_c, weather_description

WEATHER_SRC = "weather:open-meteo"
AIR_SRC = "air:open-meteo"
DERIVED_SRC = "derived:engine"

# WMO code severity ordering for choosing the "worst" weather in a slot.
_SEVERITY = {0: 0, 1: 1, 2: 2, 3: 3, 45: 4, 48: 4, 51: 5, 53: 6, 55: 7, 56: 7, 57: 8, 61: 6, 63: 8, 65: 10,
             66: 9, 67: 10, 71: 8, 73: 9, 75: 10, 77: 8, 80: 7, 81: 9, 82: 11, 85: 9, 86: 10, 95: 12, 96: 13, 99: 14}


class SeriesIndex:
    def __init__(self, series: LocationSeries | None):
        self.series = series
        self.idx = {t: i for i, t in enumerate(series.times)} if series else {}

    def values(self, var: str, start: datetime, hours: int) -> list[float | None]:
        if not self.series:
            return []
        arr = self.series.series.get(var) or []
        out = []
        for h in range(hours):
            i = self.idx.get(start + timedelta(hours=h))
            out.append(arr[i] if i is not None and i < len(arr) else None)
        return out

    def at(self, var: str, t: datetime) -> float | None:
        v = self.values(var, t, 1)
        return v[0] if v else None


def _ev(vals: list[float | None], fn, unit: str, kind: str, src: str, t: datetime, label: str) -> EvidenceValue:
    present = [v for v in vals if v is not None]
    if not vals or not present:
        return EvidenceValue.unknown(unit, f"{label} not available for this slot", src)
    note = None
    if len(present) < len(vals):
        note = f"{len(vals) - len(present)} of {len(vals)} hours missing; aggregated over available hours"
    return EvidenceValue(value=round(float(fn(present)), 1), unit=unit, kind=kind, valid_time=t, source_id=src, note=note)


def slot_hours(slot: Slot) -> int:
    return max(1, int((slot.end - slot.start).total_seconds() // 3600))


def aggregate(
    slot: Slot,
    weather: SeriesIndex,
    air: SeriesIndex,
    sun: tuple[datetime | None, datetime | None],
    prior_hours: int = 6,
) -> SlotConditions:
    n = slot_hours(slot)
    t = slot.start
    temp = weather.values("temperature_2m", t, n)
    rh = weather.values("relative_humidity_2m", t, n)
    his = [heat_index_c(a, b) for a, b in zip(temp, rh, strict=False)]
    prior = weather.values("precipitation", t - timedelta(hours=prior_hours), prior_hours)
    codes = weather.values("weather_code", t, n)
    present_codes = [c for c in codes if c is not None]
    worst = max(present_codes, key=lambda c: _SEVERITY.get(int(c), int(c) // 10)) if present_codes else None
    is_day = weather.values("is_day", t, n)
    daylight = None if not is_day or any(v is None for v in is_day) else all(v == 1 for v in is_day)
    wdir = weather.values("wind_direction_10m", t, 1)

    return SlotConditions(
        temperature_c=_ev(temp, max, "degC", "forecast", WEATHER_SRC, t, "Temperature"),
        heat_index_c=_ev(his, max, "degC", "derived", WEATHER_SRC, t, "Heat index"),
        humidity_pct=_ev(rh, max, "%", "forecast", WEATHER_SRC, t, "Humidity"),
        precip_probability_pct=_ev(weather.values("precipitation_probability", t, n), max, "%", "forecast",
                                   WEATHER_SRC, t, "Precipitation probability"),
        precip_mm=_ev(weather.values("precipitation", t, n), sum, "mm", "forecast", WEATHER_SRC, t, "Precipitation"),
        prior_precip_mm=_ev(prior, sum, "mm", "forecast", WEATHER_SRC, t - timedelta(hours=prior_hours),
                            f"Rain in the {prior_hours} h before"),
        wind_kmh=_ev(weather.values("wind_speed_10m", t, n), max, "km/h", "forecast", WEATHER_SRC, t, "Wind speed"),
        gust_kmh=_ev(weather.values("wind_gusts_10m", t, n), max, "km/h", "forecast", WEATHER_SRC, t, "Wind gusts"),
        wind_direction_deg=_ev(wdir, lambda v: v[0], "deg", "forecast", WEATHER_SRC, t, "Wind direction"),
        cloud_cover_pct=_ev(weather.values("cloud_cover", t, n), lambda v: sum(v) / len(v), "%", "forecast",
                            WEATHER_SRC, t, "Cloud cover"),
        cloud_cover_low_pct=_ev(weather.values("cloud_cover_low", t, n), lambda v: sum(v) / len(v), "%", "forecast",
                                WEATHER_SRC, t, "Low cloud cover"),
        visibility_m=_ev(weather.values("visibility", t, n), min, "m", "forecast", WEATHER_SRC, t, "Visibility"),
        uv_index=_ev(weather.values("uv_index", t, n), max, "index", "forecast", WEATHER_SRC, t, "UV index"),
        weather_code=_ev(codes, lambda v: worst, "wmo", "forecast", WEATHER_SRC, t, "Weather code"),
        weather_description=weather_description(worst),
        pm2_5=_ev(air.values("pm2_5", t, n), max, "ug/m3", "modeled", AIR_SRC, t, "PM2.5"),
        pm10=_ev(air.values("pm10", t, n), max, "ug/m3", "modeled", AIR_SRC, t, "PM10"),
        us_aqi=_ev(air.values("us_aqi", t, n), max, "US_AQI", "modeled", AIR_SRC, t, "US AQI"),
        daylight=daylight,
        sunrise=sun[0],
        sunset=sun[1],
    )


def hourly_points(weather: SeriesIndex, air: SeriesIndex, start: datetime, end: datetime) -> list[HourPoint]:
    pts = []
    t = start.replace(minute=0, second=0, microsecond=0)
    while t <= end:
        temp, rh = weather.at("temperature_2m", t), weather.at("relative_humidity_2m", t)
        day = weather.at("is_day", t)
        pts.append(HourPoint(
            time=t,
            temperature_c=temp,
            heat_index_c=heat_index_c(temp, rh),
            precip_probability_pct=weather.at("precipitation_probability", t),
            precip_mm=weather.at("precipitation", t),
            wind_kmh=weather.at("wind_speed_10m", t),
            gust_kmh=weather.at("wind_gusts_10m", t),
            cloud_cover_pct=weather.at("cloud_cover", t),
            us_aqi=air.at("us_aqi", t),
            pm2_5=air.at("pm2_5", t),
            is_day=None if day is None else bool(day),
        ))
        t += timedelta(hours=1)
    return pts

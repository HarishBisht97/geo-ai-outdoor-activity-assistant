"""Derived meteorological quantities and labels."""

from __future__ import annotations


def heat_index_c(temp_c: float | None, rh_pct: float | None) -> float | None:
    """US NWS heat index (Rothfusz regression with Steadman fallback and NWS adjustments).

    Source: https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml
    Below ~27 C (80 F) the simple formula is used; the heat index is never reported below air temperature.
    """
    if temp_c is None or rh_pct is None:
        return None
    t = temp_c * 9 / 5 + 32
    rh = max(0.0, min(100.0, rh_pct))
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    if (simple + t) / 2 < 80:
        hi = simple
    else:
        hi = (
            -42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh
            - 0.00683783 * t * t - 0.05481717 * rh * rh + 0.00122874 * t * t * rh
            + 0.00085282 * t * rh * rh - 0.00000199 * t * t * rh * rh
        )
        if rh < 13 and 80 <= t <= 112:
            hi -= ((13 - rh) / 4) * (((17 - abs(t - 95)) / 17) ** 0.5)
        elif rh > 85 and 80 <= t <= 87:
            hi += ((rh - 85) / 10) * ((87 - t) / 5)
    hi_c = (hi - 32) * 5 / 9
    return round(max(hi_c, temp_c), 1)


WMO_CODES = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    56: "light freezing drizzle", 57: "dense freezing drizzle",
    61: "slight rain", 63: "moderate rain", 65: "heavy rain",
    66: "light freezing rain", 67: "heavy freezing rain",
    71: "slight snow", 73: "moderate snow", 75: "heavy snow", 77: "snow grains",
    80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    85: "slight snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with slight hail", 99: "thunderstorm with heavy hail",
}
THUNDER_CODES = {95, 96, 99}


def weather_description(code: float | None) -> str | None:
    if code is None:
        return None
    return WMO_CODES.get(int(code), f"WMO code {int(code)}")


def compass(deg: float | None) -> str | None:
    if deg is None:
        return None
    names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return names[int(((deg % 360) + 22.5) // 45) % 8]

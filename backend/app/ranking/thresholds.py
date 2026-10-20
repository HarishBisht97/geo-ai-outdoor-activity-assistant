"""Safety thresholds with their sources. Changing a value here changes behaviour for every activity
that references it; activity-specific limits live in `activities.py`.

Sources
- Heat index bands: US National Weather Service heat index chart (Caution 80-90 F / 27-32 C,
  Extreme Caution 90-103 F / 32-39 C, Danger 103-124 F / 39-51 C).
  https://www.weather.gov/safety/heat-index  (we use 41 C as the "Danger" exclusion for strenuous activity,
  a conservative point inside the band)
- AQI categories: US EPA AQI (Good 0-50, Moderate 51-100, Unhealthy for Sensitive Groups 101-150,
  Unhealthy 151-200, Very Unhealthy 201-300, Hazardous 301+). https://www.airnow.gov/aqi/aqi-basics/
- UV index categories: WHO Global Solar UV Index (Low 0-2, Moderate 3-5, High 6-7, Very High 8-10, Extreme 11+).
- Wind: Beaufort scale - 50-61 km/h "near gale" (walking against wind becomes difficult); 62+ km/h gale.
- Thunderstorms: WMO weather codes 95/96/99; lightning guidance "When thunder roars, go indoors" (US NWS).
"""

HEAT_INDEX_CAUTION_C = 27.0
HEAT_INDEX_EXTREME_CAUTION_C = 32.0
HEAT_INDEX_DANGER_C = 41.0
HEAT_INDEX_EXTREME_DANGER_C = 46.0

AQI_MODERATE = 51
AQI_USG = 101  # Unhealthy for Sensitive Groups
AQI_UNHEALTHY = 151
AQI_VERY_UNHEALTHY = 201

UV_HIGH = 6
UV_VERY_HIGH = 8

GUST_DANGER_KMH = 62.0
GUST_STRONG_KMH = 50.0

HEAVY_RAIN_MM_PER_H = 4.0  # WMO "heavy rain" threshold is ~ >4 mm/h for showers in many national services
RAIN_LIKELY_PCT = 60

COLD_CAUTION_C = 5.0
LOW_VISIBILITY_M = 1000
VERY_LOW_VISIBILITY_M = 200

SENSITIVE_PROFILES = ("respiratory", "heat_sensitive", "children", "elderly")

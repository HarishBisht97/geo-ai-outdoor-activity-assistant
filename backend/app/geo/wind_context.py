"""Wind-relation indicator.

Meteorological wind direction is the direction the wind blows FROM. A mapped source (industrial
feature or major road) is flagged as "upwind" when its bearing from the venue lies within
+/- UPWIND_SECTOR_DEG of the wind-from direction and wind is not calm. This is a contextual indicator
only - no dispersion model is applied and no concentration is estimated.
"""

from __future__ import annotations

from app.geo.projection import angular_difference
from app.geo.spatial_context import NearbySource

UPWIND_SECTOR_DEG = 30
CALM_WIND_KMH = 5


def upwind_sources(
    sources: list[NearbySource], wind_from_deg: float | None, wind_kmh: float | None
) -> list[NearbySource]:
    if wind_from_deg is None or wind_kmh is None or wind_kmh < CALM_WIND_KMH:
        return []
    return [s for s in sources if angular_difference(s.bearing_deg, wind_from_deg) <= UPWIND_SECTOR_DEG]


def describe(src: NearbySource) -> str:
    what = {"industrial_landuse": "industrial area", "works": "industrial works", "power_plant": "power plant"}
    label = what.get(src.subtype, f"{src.subtype} road" if src.kind == "major_road" else src.subtype)
    name = f" ({src.name})" if src.name else ""
    return f"{label}{name} ~{int(src.distance_m)} m upwind"

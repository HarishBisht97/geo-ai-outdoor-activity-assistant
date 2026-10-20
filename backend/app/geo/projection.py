"""Distance and projection helpers.

- Origin-to-venue distances: haversine great-circle distance (WGS84 mean radius).
- Buffers / feature distances: a local azimuthal equidistant projection centred on the request origin.
  Within the 50 km request limit the distance distortion is far below 1%.
"""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import shapely
from pyproj import CRS, Transformer
from shapely.geometry.base import BaseGeometry

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Bearing from point 1 to point 2, degrees clockwise from north, 0..360."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def angular_difference(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings, 0..180."""
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


class LocalProjection:
    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = round(lat0, 3), round(lon0, 3)
        self._fwd, self._inv = _transformers(self.lat0, self.lon0)

    def to_local(self, geom: BaseGeometry) -> BaseGeometry:
        return _apply(self._fwd, geom)

    def to_wgs84(self, geom: BaseGeometry) -> BaseGeometry:
        return _apply(self._inv, geom)

    def point_xy(self, lat: float, lon: float) -> tuple[float, float]:
        return self._fwd.transform(lon, lat)


def _apply(tr: Transformer, geom: BaseGeometry) -> BaseGeometry:
    def fn(coords: np.ndarray) -> np.ndarray:
        x, y = tr.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(geom, fn)


@lru_cache(maxsize=64)
def _transformers(lat0: float, lon0: float) -> tuple[Transformer, Transformer]:
    aeqd = CRS.from_proj4(f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m +no_defs")
    wgs = CRS.from_epsg(4326)
    return (
        Transformer.from_crs(wgs, aeqd, always_xy=True),
        Transformer.from_crs(aeqd, wgs, always_xy=True),
    )

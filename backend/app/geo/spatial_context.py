"""Per-venue geospatial indicators computed in a local azimuthal-equidistant projection (metres).

Indicators (all `derived` from OSM):
- distance from venue centre to the nearest motorway/trunk/primary/secondary road
- industrial features within 1 km (nearest distance), and their bearing for wind-relation checks
- green-cover share of a 500 m buffer around the venue centre
- distance and bearing to the nearest mapped water body
Venue geometry is represented by its centre point (Overpass `out center`); this is stated in the notes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import Point
from shapely.ops import nearest_points, unary_union
from shapely.strtree import STRtree

from app.geo.projection import LocalProjection
from app.services.osm_context import ContextFeature

GREEN_BUFFER_M = 500
INDUSTRY_NEAR_M = 1000
SOURCE_SEARCH_M = 2000


@dataclass
class NearbySource:
    kind: str  # major_road | industrial
    subtype: str
    distance_m: float
    bearing_deg: float  # from venue towards the feature
    name: str | None = None


@dataclass
class VenueContext:
    nearest_major_road_m: float | None
    nearest_major_road_class: str | None
    nearest_industrial_m: float | None
    industrial_within_1km: bool
    green_share_500m: float | None
    nearest_water_m: float | None
    water_bearing_deg: float | None
    sources: list[NearbySource] = field(default_factory=list)


def _bearing_xy(x0: float, y0: float, x1: float, y1: float) -> float:
    return (math.degrees(math.atan2(x1 - x0, y1 - y0)) + 360) % 360


class ContextAnalyzer:
    def __init__(self, features: list[ContextFeature], origin_lat: float, origin_lon: float):
        self.proj = LocalProjection(origin_lat, origin_lon)
        self.by_kind: dict[str, list[tuple[ContextFeature, object]]] = {}
        for f in features:
            g = self.proj.to_local(f.geom)
            self.by_kind.setdefault(f.kind, []).append((f, g))
        self.trees = {k: STRtree([g for _, g in v]) for k, v in self.by_kind.items()}

    def _nearest(self, kind: str, pt: Point) -> tuple[ContextFeature, float, float] | None:
        tree = self.trees.get(kind)
        if tree is None:
            return None
        idx = tree.nearest(pt)
        if idx is None:
            return None
        feat, geom = self.by_kind[kind][int(idx)]
        p_near = nearest_points(pt, geom)[1]
        return feat, pt.distance(geom), _bearing_xy(pt.x, pt.y, p_near.x, p_near.y)

    def _within(self, kind: str, pt: Point, radius: float) -> list[tuple[ContextFeature, float, float]]:
        tree = self.trees.get(kind)
        if tree is None:
            return []
        out = []
        for idx in tree.query(pt.buffer(radius)):
            feat, geom = self.by_kind[kind][int(idx)]
            d = pt.distance(geom)
            if d <= radius:
                p_near = nearest_points(pt, geom)[1]
                out.append((feat, d, _bearing_xy(pt.x, pt.y, p_near.x, p_near.y)))
        return sorted(out, key=lambda t: t[1])

    def analyze(self, lat: float, lon: float) -> VenueContext:
        x, y = self.proj.point_xy(lat, lon)
        pt = Point(x, y)
        road = self._nearest("major_road", pt)
        ind = self._nearest("industrial", pt)
        water = self._nearest("water", pt)

        green_share = 0.0
        greens = self.by_kind.get("green", [])
        if greens:
            buf = pt.buffer(GREEN_BUFFER_M, quad_segs=16)
            hits = [g for idx in self.trees["green"].query(buf) for g in [greens[int(idx)][1]]
                    if g.geom_type in ("Polygon", "MultiPolygon")]
            if hits:
                inter = unary_union(hits).intersection(buf)
                green_share = min(1.0, inter.area / buf.area)

        sources = []
        for feat, d, b in self._within("industrial", pt, SOURCE_SEARCH_M)[:5]:
            sources.append(NearbySource("industrial", feat.subtype, round(d), round(b), feat.name))
        for feat, d, b in self._within("major_road", pt, 300)[:3]:
            sources.append(NearbySource("major_road", feat.subtype, round(d), round(b), feat.name))

        return VenueContext(
            nearest_major_road_m=round(road[1]) if road else None,
            nearest_major_road_class=road[0].subtype if road else None,
            nearest_industrial_m=round(ind[1]) if ind else None,
            industrial_within_1km=bool(ind and ind[1] <= INDUSTRY_NEAR_M),
            green_share_500m=round(green_share, 3),
            nearest_water_m=round(water[1]) if water else None,
            water_bearing_deg=round(water[2]) if water else None,
            sources=sources,
        )

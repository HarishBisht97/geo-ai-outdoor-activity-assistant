"""Surrounding-feature extraction (roads, industry, water, green cover) for candidate venues via Overpass."""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

from app.schemas.common import Provenance
from app.services.base import ServiceDeps
from app.services.overpass import run_query

ROAD_RADIUS_M = 1000
INDUSTRY_RADIUS_M = 2000
WATER_RADIUS_M = 2000
GREEN_RADIUS_M = 600


@dataclass
class ContextFeature:
    kind: str  # major_road | industrial | water | green
    subtype: str
    geom: BaseGeometry  # WGS84 lon/lat
    name: str | None


def build_context_query(points: list[tuple[float, float]], timeout_s: int = 25) -> str:
    stmts = []
    for lat, lon in points:
        c = f"{lat:.5f},{lon:.5f}"
        stmts += [
            f'way["highway"~"^(motorway|trunk|primary|secondary)$"](around:{ROAD_RADIUS_M},{c});',
            f'nwr["landuse"="industrial"](around:{INDUSTRY_RADIUS_M},{c});',
            f'nwr["man_made"="works"](around:{INDUSTRY_RADIUS_M},{c});',
            f'nwr["power"="plant"](around:{INDUSTRY_RADIUS_M},{c});',
            f'nwr["natural"="water"](around:{WATER_RADIUS_M},{c});',
            f'way["waterway"~"^(river|canal)$"](around:{WATER_RADIUS_M},{c});',
            f'nwr["leisure"~"^(park|garden|nature_reserve)$"](around:{GREEN_RADIUS_M},{c});',
            f'nwr["landuse"~"^(forest|grass|meadow|recreation_ground)$"](around:{GREEN_RADIUS_M},{c});',
            f'nwr["natural"~"^(wood|scrub|grassland)$"](around:{GREEN_RADIUS_M},{c});',
        ]
    body = "\n  ".join(stmts)
    return f"[out:json][timeout:{timeout_s}][maxsize:67108864];\n(\n  {body}\n);\nout tags geom qt;"


def _classify(tags: dict[str, str]) -> tuple[str, str] | None:
    hw = tags.get("highway")
    if hw in ("motorway", "trunk", "primary", "secondary"):
        return "major_road", hw
    if tags.get("landuse") == "industrial":
        return "industrial", "industrial_landuse"
    if tags.get("man_made") == "works":
        return "industrial", "works"
    if tags.get("power") == "plant":
        return "industrial", "power_plant"
    if tags.get("natural") == "water":
        return "water", tags.get("water", "water")
    if tags.get("waterway") in ("river", "canal"):
        return "water", tags["waterway"]
    if tags.get("leisure") in ("park", "garden", "nature_reserve"):
        return "green", tags["leisure"]
    if tags.get("landuse") in ("forest", "grass", "meadow", "recreation_ground"):
        return "green", tags["landuse"]
    if tags.get("natural") in ("wood", "scrub", "grassland"):
        return "green", tags["natural"]
    return None


def _coords(geometry: list[dict]) -> list[tuple[float, float]]:
    return [(g["lon"], g["lat"]) for g in geometry if g and "lat" in g and "lon" in g]


def _element_geometry(el: dict, areal: bool) -> BaseGeometry | None:
    t = el.get("type")
    if t == "node":
        return Point(el["lon"], el["lat"]) if "lat" in el else None
    if t == "way":
        pts = _coords(el.get("geometry") or [])
        if len(pts) < 2:
            return None
        if areal and len(pts) >= 4 and pts[0] == pts[-1]:
            poly = Polygon(pts)
            return poly if poly.is_valid else poly.buffer(0)
        return LineString(pts)
    if t == "relation":
        lines = []
        for m in el.get("members") or []:
            if m.get("type") == "way" and m.get("role", "outer") in ("outer", ""):
                pts = _coords(m.get("geometry") or [])
                if len(pts) >= 2:
                    lines.append(LineString(pts))
        if not lines:
            return None
        if areal:
            polys = list(polygonize(unary_union(lines)))
            if polys:
                return unary_union(polys)
        return unary_union(lines)
    return None


def parse_context(payload: dict) -> list[ContextFeature]:
    feats: list[ContextFeature] = []
    seen: set[tuple[str, int]] = set()
    for el in (payload or {}).get("elements", []):
        key = (el.get("type"), el.get("id"))
        if key in seen:
            continue
        seen.add(key)
        tags = el.get("tags") or {}
        cls = _classify(tags)
        if cls is None:
            continue
        kind, subtype = cls
        areal = kind in ("industrial", "green") or (kind == "water" and subtype not in ("river", "canal"))
        try:
            geom = _element_geometry(el, areal)
        except (ValueError, KeyError, TypeError):
            geom = None
        if geom is None or geom.is_empty:
            continue
        feats.append(ContextFeature(kind, subtype, geom, tags.get("name")))
    return feats


async def fetch_context(
    deps: ServiceDeps, points: list[tuple[float, float]]
) -> tuple[list[ContextFeature] | None, Provenance]:
    rounded = sorted({(round(lat, 4), round(lon, 4)) for lat, lon in points})
    ql = build_context_query(rounded)
    fetched = await run_query(deps, ql, pid="context:overpass", ttl=deps.settings.cache_ttl_context,
                              budget_s=deps.settings.overpass_context_budget_s)
    if not fetched.ok:
        return None, fetched.provenance
    fetched.provenance.limitations.append(
        "Road, industrial, water and green features are mapped context only; they are not traffic or "
        "pollution measurements."
    )
    return parse_context(fetched.data), fetched.provenance

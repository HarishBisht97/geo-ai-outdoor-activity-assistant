"""Candidate venue generation: Overpass query building, parsing, deduplication and pre-filtering."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from app.geo.activity_tags import ACTIVITY_SELECTORS, ALLOWED_TAGS, CATEGORY_LABELS, TagSelector
from app.geo.projection import EARTH_RADIUS_KM, haversine_km
from app.schemas.common import Coordinates
from app.schemas.venue import Venue

EXCLUDED_ACCESS = {"private", "no"}
RESTRICTED_ACCESS = {"customers", "members", "permit", "destination"}
NAME_REQUIRED_RADIUS_KM = 5.0


@dataclass
class RawPlace:
    osm_type: str
    osm_id: int
    name: str | None
    lat: float
    lon: float
    tags: dict[str, str]
    selector: TagSelector
    selector_rank: int
    area_m2: float | None
    distance_km: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def uid(self) -> str:
        return f"osm:{self.osm_type}:{self.osm_id}"


def build_places_query(profile_key: str, lat: float, lon: float, radius_km: float, timeout_s: int = 25) -> str:
    r = int(radius_km * 1000)
    lines = []
    for sel in ACTIVITY_SELECTORS[profile_key]:
        ql = sel.ql
        if sel.generic and radius_km > NAME_REQUIRED_RADIUS_KM and '["name"]' not in ql:
            ql += '["name"]'
        lines.append(f"  {ql}(around:{r},{lat:.6f},{lon:.6f});")
    body = "\n".join(lines)
    return f"[out:json][timeout:{timeout_s}];\n(\n{body}\n);\nout tags center bb qt;"


def _matches(sel: TagSelector, tags: dict[str, str], osm_type: str) -> bool:
    """Client-side re-check of which selector an element satisfies (Overpass unions lose that)."""
    type_part, *filters = re.findall(r"^(\w+)|\[([^\]]+)\]", sel.ql)
    elem_kind = type_part[0]
    if elem_kind != "nwr" and elem_kind != osm_type:
        return False
    for _, f in filters:
        if f.startswith("!"):
            if f[1:].strip('"') in tags:
                return False
            continue
        m = re.match(r'"([^"]+)"(!?[=~])"([^"]*)"$', f)
        if not m:
            key = f.strip('"')
            if key not in tags:
                return False
            continue
        key, op, val = m.groups()
        actual = tags.get(key)
        if op == "=":
            if actual != val:
                return False
        elif op == "~":
            if actual is None or not re.search(val, actual):
                return False
        elif op == "!=":
            if actual == val:
                return False
        elif op == "!~" and actual is not None and re.search(val, actual):
            return False
    return True


def bbox_area_m2(bounds: dict | None) -> float | None:
    if not bounds:
        return None
    try:
        lat1, lat2 = float(bounds["minlat"]), float(bounds["maxlat"])
        lon1, lon2 = float(bounds["minlon"]), float(bounds["maxlon"])
    except (KeyError, TypeError, ValueError):
        return None
    h = math.radians(lat2 - lat1) * EARTH_RADIUS_KM * 1000
    w = math.radians(lon2 - lon1) * EARTH_RADIUS_KM * 1000 * math.cos(math.radians((lat1 + lat2) / 2))
    return abs(h * w)


def parse_places(payload: dict, profile_key: str, origin: Coordinates, radius_km: float) -> list[RawPlace]:
    selectors = ACTIVITY_SELECTORS[profile_key]
    places: dict[str, RawPlace] = {}
    for el in (payload or {}).get("elements", []):
        osm_type, osm_id = el.get("type"), el.get("id")
        tags = el.get("tags") or {}
        if osm_type not in ("node", "way", "relation") or osm_id is None:
            continue
        if osm_type == "node":
            lat, lon = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            lat, lon = c.get("lat"), c.get("lon")
        if lat is None or lon is None:
            continue
        if tags.get("access") in EXCLUDED_ACCESS:
            continue
        rank = next((i for i, s in enumerate(selectors) if _matches(s, tags, osm_type)), None)
        if rank is None:
            continue
        sel = selectors[rank]
        area = bbox_area_m2(el.get("bounds")) if osm_type != "node" else None
        if sel.min_area_m2 and (area is None or area < sel.min_area_m2):
            continue
        dist = haversine_km(origin.lat, origin.lon, lat, lon)
        if dist > radius_km:
            continue
        name = (tags.get("name:en") or tags.get("name") or "").strip() or None
        p = RawPlace(osm_type, int(osm_id), name, float(lat), float(lon), tags, sel, rank, area, dist)
        if tags.get("access") in RESTRICTED_ACCESS:
            p.notes.append(f"Access is mapped as '{tags['access']}' - entry may be restricted.")
        if tags.get("fee") == "yes":
            p.notes.append("An entry or usage fee is mapped.")
        existing = places.get(p.uid)
        if existing is None or p.selector_rank < existing.selector_rank:
            places[p.uid] = p
    return list(places.values())


def _norm(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _quality(p: RawPlace) -> tuple:
    return (
        p.selector.suitability == "explicit",
        p.name is not None,
        p.osm_type != "node",
        p.area_m2 or 0,
        -p.selector_rank,
        -p.osm_id,
    )


def dedupe(places: list[RawPlace], same_name_m: float = 300, same_category_m: float = 150) -> list[RawPlace]:
    """Drop near-duplicates: same name within 300 m, or same category within 150 m (keeps the better one)."""
    ordered = sorted(places, key=_quality, reverse=True)
    kept: list[RawPlace] = []
    for p in ordered:
        dup = False
        for k in kept:
            d_m = haversine_km(p.lat, p.lon, k.lat, k.lon) * 1000
            if p.name and k.name and _norm(p.name) == _norm(k.name) and d_m <= same_name_m or p.selector.category == k.selector.category and d_m <= same_category_m:
                dup = True
            if dup:
                break
        if not dup:
            kept.append(p)
    return kept


def prefilter(places: list[RawPlace], radius_km: float, max_candidates: int) -> list[RawPlace]:
    """Bound evidence fetching: rank by explicit suitability, naming, size and proximity."""

    def score(p: RawPlace) -> float:
        s = 1.0 if p.selector.suitability == "explicit" else 0.6
        s += 0.15 if p.name else 0.0
        if p.area_m2:
            s += min(0.15, math.log10(max(p.area_m2, 1)) / 40)
        s -= 0.5 * (p.distance_km / max(radius_km, 0.1))
        return s

    ranked = sorted(places, key=lambda p: (-score(p), p.distance_km, p.uid))
    explicit = [p for p in ranked if p.selector.suitability == "explicit"]
    inferred = [p for p in ranked if p.selector.suitability != "explicit"]
    max_inferred = max_candidates // 2 if explicit else max_candidates
    chosen = explicit[:max_candidates]
    chosen += inferred[: max(0, min(max_inferred, max_candidates - len(chosen)))]
    return sorted(chosen, key=lambda p: (-score(p), p.distance_km, p.uid))


def to_venue(p: RawPlace, source_id: str) -> Venue:
    cat_label = CATEGORY_LABELS.get(p.selector.category, p.selector.category.replace("_", " "))
    label = p.name or f"Unnamed {cat_label} (OSM {p.osm_type} {p.osm_id})"
    note_parts = []
    if p.selector.note:
        note_parts.append(p.selector.note)
    note_parts.extend(p.notes)
    return Venue(
        id=p.uid,
        name=p.name,
        display_label=label,
        coords=Coordinates(lat=round(p.lat, 6), lon=round(p.lon, 6)),
        osm_type=p.osm_type,  # type: ignore[arg-type]
        osm_id=p.osm_id,
        osm_url=f"https://www.openstreetmap.org/{p.osm_type}/{p.osm_id}",
        tags={k: v for k, v in p.tags.items() if k in ALLOWED_TAGS},
        category=p.selector.category,
        suitability=p.selector.suitability,  # type: ignore[arg-type]
        suitability_note=" ".join(note_parts) or None,
        area_m2=round(p.area_m2, 0) if p.area_m2 else None,
        distance_km=round(p.distance_km, 2),
        source_id=source_id,
    )

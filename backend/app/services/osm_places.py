"""Candidate venue search.

Primary source is Overpass. Public Overpass instances are frequently overloaded (30-50 s responses or
502/504), so the search is hedged: if Overpass has not answered after `places_hedge_after_s`, the same
OSM main tags are also searched through Nominatim (`[key=value]` special-phrase search, bounded to the
search box). Overpass is preferred when it answers within the grace period; otherwise the Nominatim
results are used and the Overpass query keeps running in the background so it lands in the cache.
Both paths return real OSM objects; nothing is synthesised.
"""

from __future__ import annotations

import asyncio
import math
import re
import time

from app.core.errors import ProviderError
from app.geo.activity_tags import ACTIVITY_SELECTORS, TagSelector
from app.geo.candidates import RawPlace, build_places_query, dedupe, parse_places, prefilter
from app.geo.projection import EARTH_RADIUS_KM
from app.schemas.common import Coordinates, Provenance
from app.services.base import OSM_ATTRIBUTION, Fetched, ServiceDeps, keep_running, make_provenance
from app.services.overpass import run_query

MAX_FALLBACK_TAGS = 6
NOMINATIM_LIMIT = 40


def main_tags(sel: TagSelector) -> list[tuple[str, str]]:
    """The first key/value filter of a selector, expanded to plain (key, value) pairs."""
    m = re.match(r'^\w+\["([^"]+)"([=~])"([^"]+)"\]', sel.ql)
    if not m:
        return []
    key, op, val = m.groups()
    if op == "=":
        return [(key, val)]
    return [(key, v) for v in val.strip("^$").strip("()").split("|") if re.fullmatch(r"[a-z_]+", v)]


def fallback_tags(profile_key: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for sel in ACTIVITY_SELECTORS[profile_key]:
        for kv in main_tags(sel):
            if kv not in out:
                out.append(kv)
    return out[:MAX_FALLBACK_TAGS]


def viewbox(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    dlat = math.degrees(radius_km / EARTH_RADIUS_KM)
    dlon = dlat / max(math.cos(math.radians(lat)), 0.01)
    return lon - dlon, lat + dlat, lon + dlon, lat - dlat


def nominatim_to_elements(results: list[dict]) -> list[dict]:
    """Shape Nominatim jsonv2 results like Overpass `out tags center bb` elements."""
    elements = []
    for r in results or []:
        try:
            osm_type, osm_id = r["osm_type"], int(r["osm_id"])
            lat, lon = float(r["lat"]), float(r["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        tags = {k: str(v) for k, v in (r.get("extratags") or {}).items()}
        if r.get("category") and r.get("type"):
            tags[r["category"]] = r["type"]
        if r.get("name"):
            tags["name"] = r["name"]
        el: dict = {"type": osm_type, "id": osm_id, "tags": tags}
        if osm_type == "node":
            el.update(lat=lat, lon=lon)
        else:
            el["center"] = {"lat": lat, "lon": lon}
            bb = r.get("boundingbox")
            if bb and len(bb) == 4:
                el["bounds"] = {"minlat": bb[0], "maxlat": bb[1], "minlon": bb[2], "maxlon": bb[3]}
        elements.append(el)
    return elements


async def nominatim_places(deps: ServiceDeps, profile_key: str, lat: float, lon: float,
                           radius_km: float) -> Fetched[dict]:
    s = deps.settings
    url = f"{s.nominatim_url}/search"
    vb = viewbox(lat, lon, radius_km)
    vb_s = ",".join(f"{v:.4f}" for v in vb)
    elements: list[dict] = []
    failures = 0
    hits = 0
    tags = fallback_tags(profile_key)
    for key, val in tags:
        params = {"q": f"[{key}={val}]", "viewbox": vb_s, "bounded": 1, "format": "jsonv2",
                  "limit": NOMINATIM_LIMIT, "extratags": 1}
        if s.contact_email:
            params["email"] = s.contact_email

        async def fetch(params=params):
            return await deps.http.fetch_json("nominatim", url, params=params, retries=1)

        try:
            (payload, _), hit = await deps.cache.get_or_fetch(f"poi:{key}={val}:{vb_s}", s.cache_ttl_places, fetch)
        except ProviderError:
            failures += 1
            continue
        hits += hit
        elements += nominatim_to_elements(payload)
    status = "failed" if failures == len(tags) else ("partial" if failures else "ok")
    prov = make_provenance(
        "places:nominatim", "OpenStreetMap via Nominatim search (fallback)", url=url, kind="observed",
        license="ODbL 1.0", attribution=OSM_ATTRIBUTION, cache_hit=bool(tags) and hits == len(tags), status=status,
        limitations=[
            "Used because the Overpass API did not respond in time.",
            f"At most {NOMINATIM_LIMIT} results per tag, ordered by Nominatim importance; smaller or less "
            "prominent venues may be missing, and route relations are not covered.",
            "OSM coverage and tagging are volunteer-maintained and may be incomplete or outdated.",
        ],
        error=f"{failures} of {len(tags)} tag searches failed" if failures else None,
    )
    return Fetched(None if status == "failed" else {"elements": elements}, prov)


def requested_venue(raw: dict | None, profile_key: str, origin: Coordinates) -> RawPlace | None:
    """The geocoded place itself, when it is a mapped feature suitable for the activity (e.g. 'in Cubbon Park')."""
    if not raw:
        return None
    places = parse_places({"elements": nominatim_to_elements([raw])}, profile_key, origin, radius_km=1e6)
    return places[0] if places else None


def pin_requested(places: list[RawPlace], target: RawPlace, max_candidates: int) -> list[RawPlace]:
    """Put the requested venue first; drop search results that are the same feature or a same-named duplicate."""
    same_name = (target.name or "").casefold()
    rest = [p for p in places if p.uid != target.uid and not (same_name and (p.name or "").casefold() == same_name)]
    return [target, *rest][:max_candidates]


async def _search(deps: ServiceDeps, profile_key: str, lat: float, lon: float, radius_km: float
                  ) -> tuple[Fetched, list[Provenance]]:
    """Returns (fetched result used, provenance of every source consulted)."""
    s = deps.settings
    t0 = time.monotonic()
    ql = build_places_query(profile_key, lat, lon, radius_km)
    overpass = asyncio.create_task(
        run_query(deps, ql, pid="places:overpass", ttl=s.cache_ttl_places, budget_s=s.overpass_budget_s))
    done, _ = await asyncio.wait({overpass}, timeout=s.places_hedge_after_s)
    if overpass in done and overpass.result().ok:
        return overpass.result(), [overpass.result().provenance]

    fallback = await nominatim_places(deps, profile_key, lat, lon, radius_km)
    if not overpass.done() and fallback.ok and fallback.data["elements"]:
        await asyncio.wait({overpass}, timeout=max(0.0, s.places_prefer_overpass_s - (time.monotonic() - t0)))
    if overpass.done():
        primary = overpass.result()
        if primary.ok:
            return primary, [primary.provenance]
        return fallback, [fallback.provenance, primary.provenance]
    if fallback.ok and fallback.data["elements"]:
        keep_running(overpass)
        pending = make_provenance("places:overpass", "OpenStreetMap via Overpass API", url=s.overpass_mirrors[0],
                                  kind="observed", license="ODbL 1.0", attribution=OSM_ATTRIBUTION,
                                  status="skipped", error="No response within the time budget; fallback used.")
        return fallback, [fallback.provenance, pending]
    primary = await overpass
    return (primary if primary.ok else fallback), [primary.provenance, fallback.provenance]


async def find_candidates(
    deps: ServiceDeps, profile_key: str, origin: Coordinates, radius_km: float
) -> tuple[list[RawPlace], int, list[Provenance]]:
    """Returns (pre-filtered candidates, number found after de-duplication, provenances).

    The first provenance is the source the candidates came from.
    """
    lat, lon = round(origin.lat, 3), round(origin.lon, 3)
    fetched, provs = await _search(deps, profile_key, lat, lon, radius_km)
    if not fetched.ok:
        return [], 0, provs
    parsed = parse_places(fetched.data, profile_key, origin, radius_km)
    unique = dedupe(parsed)
    chosen = prefilter(unique, radius_km, deps.settings.max_candidates)
    prov = provs[0].model_copy(deep=True)
    prov.limitations.append(
        f"{len(parsed)} mapped features matched; {len(unique)} after de-duplication; "
        f"{len(chosen)} evaluated in detail."
    )
    return chosen, len(unique), [prov, *provs[1:]]

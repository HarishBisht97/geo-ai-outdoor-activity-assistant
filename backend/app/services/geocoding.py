"""Nominatim geocoding adapter.

Policy (https://operations.osmfoundation.org/policies/nominatim/): <= 1 request/second, identifying
User-Agent, cache results, no autocomplete. Enforced by HostThrottle + a 7 day cache.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ProviderError
from app.geo.projection import haversine_km
from app.services.base import OSM_ATTRIBUTION, Fetched, ServiceDeps, make_provenance


@dataclass
class GeocodeResult:
    label: str
    display_name: str
    lat: float
    lon: float
    importance: float
    osm_type: str | None
    osm_id: int | None
    place_type: str | None
    raw: dict | None = None  # the Nominatim jsonv2 record (class/type, bounding box, extratags)


@dataclass
class GeocodeDecision:
    chosen: GeocodeResult | None
    options: list[GeocodeResult]
    reason: str  # "unique" | "clustered" | "urban_preferred" | "ambiguous" | "not_found"


# Equal-importance name clashes are common (an urban suburb vs. several villages of the same name); when
# exactly one contender is urban and the rest are rural, the urban one is chosen and stated as an assumption.
URBAN_TYPES = {"city", "town", "suburb", "neighbourhood", "quarter", "city_district", "borough"}
RURAL_TYPES = {"village", "hamlet", "isolated_dwelling", "farm", "locality"}


def _short_label(display_name: str) -> str:
    parts = [p.strip() for p in display_name.split(",") if p.strip()]
    return ", ".join(parts[:3]) if parts else display_name


async def geocode(deps: ServiceDeps, query: str) -> Fetched[list[GeocodeResult]]:
    s = deps.settings
    q = " ".join(query.split())
    params = {"q": q, "format": "jsonv2", "limit": 5, "addressdetails": 0, "extratags": 1}
    if s.geocoder_country_bias:
        params["countrycodes"] = s.geocoder_country_bias
    if s.contact_email:
        params["email"] = s.contact_email
    url = f"{s.nominatim_url}/search"
    key = f"geocode:{s.geocoder_country_bias}:{q.lower()}"

    async def fetch():
        payload, used = await deps.http.fetch_json("nominatim", url, params=params)
        return payload, used

    try:
        (payload, used), hit = await deps.cache.get_or_fetch(key, s.cache_ttl_geocode, fetch)
    except ProviderError as exc:
        return Fetched(
            None,
            make_provenance("geocode:nominatim", "Nominatim (OpenStreetMap)", url=url, kind="observed",
                            license="ODbL 1.0", attribution=OSM_ATTRIBUTION, status="failed", error=exc.message),
        )
    results = []
    for r in payload or []:
        try:
            results.append(
                GeocodeResult(
                    label=_short_label(r.get("display_name", q)),
                    display_name=r.get("display_name", q),
                    lat=float(r["lat"]),
                    lon=float(r["lon"]),
                    importance=float(r.get("importance") or 0.0),
                    osm_type=r.get("osm_type"),
                    osm_id=int(r["osm_id"]) if r.get("osm_id") is not None else None,
                    place_type=r.get("addresstype") or r.get("type"),
                    raw=r,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    prov = make_provenance(
        "geocode:nominatim", "Nominatim (OpenStreetMap)", url=used, kind="observed", license="ODbL 1.0",
        attribution=OSM_ATTRIBUTION, cache_hit=hit,
        limitations=["Geocoding matches OSM names; ambiguous names are confirmed with the user."],
    )
    return Fetched(results, prov)


def decide(results: list[GeocodeResult], cluster_km: float = 3.0, importance_ratio: float = 0.6,
           same_area_km: float = 8.0) -> GeocodeDecision:
    """Pick a result only when it is unambiguous; otherwise return distinct options for clarification."""
    if not results:
        return GeocodeDecision(None, [], "not_found")
    ranked = sorted(results, key=lambda r: r.importance, reverse=True)
    top = ranked[0]
    clusters: list[GeocodeResult] = [top]
    for r in ranked[1:]:
        if all(haversine_km(r.lat, r.lon, c.lat, c.lon) > cluster_km for c in clusters):
            clusters.append(r)
    if len(clusters) == 1:
        return GeocodeDecision(top, [], "unique" if len(ranked) == 1 else "clustered")
    rivals = [c for c in clusters[1:] if c.importance >= importance_ratio * top.importance]
    if not rivals:
        return GeocodeDecision(top, [], "clustered")
    contenders = [top, *rivals]
    if all(haversine_km(top.lat, top.lon, r.lat, r.lon) <= same_area_km for r in rivals):
        # e.g. a suburb and its railway stations: one place; prefer the area over a point of interest
        area = [c for c in contenders if c.place_type in URBAN_TYPES]
        return GeocodeDecision(area[0] if area else top, [], "clustered")
    urban = [c for c in contenders if c.place_type in URBAN_TYPES]
    if len(urban) == 1 and all(c.place_type in RURAL_TYPES for c in contenders if c is not urban[0]):
        return GeocodeDecision(urban[0], [c for c in clusters if c is not urban[0]][:3], "urban_preferred")
    return GeocodeDecision(None, clusters[:4], "ambiguous")

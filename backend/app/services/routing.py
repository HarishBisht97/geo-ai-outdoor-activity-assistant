"""OSRM table-service adapter: one origin -> N venues in a single request.

Public demo servers (router.project-osrm.org for driving; routing.openstreetmap.de for foot/bike)
allow light use only (<= 1 req/s). OSRM computes free-flow times from OSM road data: there is no live
traffic. When routing fails the pipeline shows straight-line distance only and marks travel time unknown.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ProviderError
from app.schemas.intent import TravelMode
from app.services.base import OSM_ATTRIBUTION, Fetched, ServiceDeps, make_provenance


@dataclass
class RouteLeg:
    duration_s: float | None
    distance_m: float | None


def _base_url(deps: ServiceDeps, mode: TravelMode) -> tuple[str, str]:
    s = deps.settings
    if mode == "walking":
        return s.osrm_foot_url, "driving"  # FOSSGIS servers expose one profile per base path
    if mode == "cycling":
        return s.osrm_bike_url, "driving"
    return s.osrm_driving_url, "driving"


async def route_table(
    deps: ServiceDeps, origin: tuple[float, float], destinations: list[tuple[float, float]], mode: TravelMode
) -> Fetched[list[RouteLeg]]:
    pid = f"routing:osrm:{mode}"
    base, profile = _base_url(deps, mode)
    if not destinations:
        return Fetched([], make_provenance(pid, "OSRM", url=None, kind="derived", license="ODbL 1.0",
                                           attribution=OSM_ATTRIBUTION, status="skipped"))
    pts = [origin, *destinations]
    coord_str = ";".join(f"{lon:.5f},{lat:.5f}" for lat, lon in pts)
    url = f"{base}/table/v1/{profile}/{coord_str}"
    params = {"sources": "0", "annotations": "duration,distance"}
    key = f"osrm:{mode}:{coord_str}"
    limitations = [
        "Free-flow travel time from OSM road network; no live traffic data.",
        "Public demo routing server; availability is best-effort.",
    ]

    async def fetch():
        return await deps.http.fetch_json("osrm", url, params=params)

    try:
        (payload, used), hit = await deps.cache.get_or_fetch(key, deps.settings.cache_ttl_routing, fetch)
    except ProviderError as exc:
        return Fetched(None, make_provenance(pid, "OSRM", url=url, kind="derived", license="ODbL 1.0",
                                             attribution=OSM_ATTRIBUTION, status="failed", error=exc.message,
                                             limitations=limitations))
    if payload.get("code") != "Ok":
        return Fetched(None, make_provenance(pid, "OSRM", url=used, kind="derived", license="ODbL 1.0",
                                             attribution=OSM_ATTRIBUTION, status="failed",
                                             error=str(payload.get("code")), limitations=limitations))
    durations = (payload.get("durations") or [[]])[0][1:]
    distances = (payload.get("distances") or [[]])[0][1:]
    legs = [
        RouteLeg(
            duration_s=durations[i] if i < len(durations) else None,
            distance_m=distances[i] if i < len(distances) else None,
        )
        for i in range(len(destinations))
    ]
    status = "ok" if all(leg.duration_s is not None for leg in legs) else "partial"
    return Fetched(legs, make_provenance(pid, "OSRM", url=used, kind="derived", license="ODbL 1.0",
                                         attribution=OSM_ATTRIBUTION, cache_hit=hit, status=status,
                                         limitations=limitations))

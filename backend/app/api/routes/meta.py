from __future__ import annotations

from fastapi import APIRouter

from app.geo.activity_tags import ACTIVITY_SELECTORS
from app.ranking.activities import NATURE_WALK, PROFILES

router = APIRouter(prefix="/api/v1", tags=["metadata"])

DATA_SOURCES = [
    {"id": "geocode:nominatim", "name": "Nominatim (OpenStreetMap)", "url": "https://nominatim.org",
     "purpose": "Place-name geocoding", "license": "ODbL 1.0", "credentials": "none",
     "limits": "<= 1 request/s, identifying User-Agent, results cached 7 days"},
    {"id": "places:overpass", "name": "Overpass API (OpenStreetMap)", "url": "https://overpass-api.de",
     "purpose": "Candidate venues and surrounding features", "license": "ODbL 1.0", "credentials": "none",
     "limits": "Fair use (~10k queries/day, 2 slots); mirrors used on failure; cached 24 h"},
    {"id": "places:nominatim", "name": "Nominatim search (OpenStreetMap), venue fallback",
     "url": "https://nominatim.org", "purpose": "Candidate venues when Overpass does not respond in time",
     "license": "ODbL 1.0", "credentials": "none",
     "limits": "<= 1 request/s, at most 40 results per tag (importance-ordered), cached 24 h"},
    {"id": "weather:open-meteo", "name": "Open-Meteo Forecast API", "url": "https://open-meteo.com",
     "purpose": "Hourly weather forecast, sunrise and sunset", "license": "CC BY 4.0", "credentials": "none",
     "limits": "Non-commercial free tier < 10,000 calls/day; cached 30 min"},
    {"id": "air:open-meteo", "name": "Open-Meteo Air Quality API (Copernicus CAMS)",
     "url": "https://open-meteo.com/en/docs/air-quality-api", "purpose": "Modelled PM2.5, PM10, NO2, O3, US AQI",
     "license": "CC BY 4.0", "credentials": "none", "limits": "~5-day coverage, ~45 km resolution outside Europe"},
    {"id": "elevation:open-meteo", "name": "Open-Meteo Elevation API", "url": "https://open-meteo.com/en/docs/elevation-api",
     "purpose": "Venue elevation (hiking, photography)", "license": "CC BY 4.0", "credentials": "none",
     "limits": "Up to 100 coordinates per call"},
    {"id": "routing:osrm", "name": "OSRM public servers", "url": "https://project-osrm.org",
     "purpose": "Free-flow travel time and distance", "license": "ODbL 1.0 (OSM data)", "credentials": "none",
     "limits": "Demo servers, <= 1 request/s, no live traffic"},
]


@router.get("/activities", summary="Supported activities and their scoring rules")
async def activities() -> list[dict]:
    out = []
    for key, p in [*[(a.value, p) for a, p in PROFILES.items()], ("nature_walk", NATURE_WALK)]:
        out.append({
            "key": key, "activity": p.activity.value, "label": p.label, "description": p.description,
            "default_radius_km": p.default_radius_km, "max_radius_km": p.max_radius_km,
            "duration_min": p.duration_min, "strenuous": p.strenuous, "daylight": p.daylight,
            "gust_limit_kmh": p.gust_max_kmh, "weights": p.weights, "rationale": list(p.rationale),
            "osm_selectors": [s.ql for s in ACTIVITY_SELECTORS[key]],
        })
    return out


@router.get("/sources", summary="External data sources, purposes, licences and limits")
async def sources() -> list[dict]:
    return DATA_SOURCES

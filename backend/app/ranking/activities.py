"""Activity rule registry.

Each profile declares: venue requirements (see geo/activity_tags.py), duration, daylight policy,
component weights (normalised at scoring time), activity-specific hard limits and base advice.
Weights express *relative* importance; they are design assumptions documented in docs/scoring-rules.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.ranking import curves
from app.schemas.intent import Activity, TravelMode

Daylight = Literal["required", "preferred", "any", "golden_hour"]


@dataclass(frozen=True)
class ActivityProfile:
    activity: Activity
    label: str
    description: str
    default_radius_km: float
    max_radius_km: float
    duration_min: int
    strenuous: bool
    daylight: Daylight
    default_travel_mode: TravelMode
    weights: dict[str, float]
    heat_curve: curves.Curve = curves.HEAT_STRENUOUS
    wind_curve: curves.Curve = curves.WIND_GENERAL
    gust_max_kmh: float = 62.0
    thunder_buffer_h: int = 0
    prior_rain_hours: int = 0
    end_before_sunset_min: int | None = None
    heavy_rain_excludes: bool = True
    base_advice: tuple[str, ...] = ()
    rationale: tuple[str, ...] = field(default_factory=tuple)


PROFILES: dict[Activity, ActivityProfile] = {
    Activity.running: ActivityProfile(
        Activity.running, "Running / jogging", "Parks, tracks and green routes for a run.",
        default_radius_km=5, max_radius_km=20, duration_min=60, strenuous=True, daylight="preferred",
        default_travel_mode="walking",
        weights={"thermal": 0.30, "air_quality": 0.25, "precipitation": 0.15, "daylight": 0.10,
                 "travel": 0.10, "context": 0.05, "wind": 0.05, "venue_fit": 0.05},
        base_advice=("Carry water and start slower than usual if it is humid.",),
        rationale=("Heat stress and air quality matter most for sustained aerobic effort.",),
    ),
    Activity.cycling: ActivityProfile(
        Activity.cycling, "Cycling (recreational or commuting)", "Cycleways, cycle routes and large parks.",
        default_radius_km=10, max_radius_km=30, duration_min=60, strenuous=True, daylight="preferred",
        default_travel_mode="cycling",
        weights={"precipitation": 0.25, "wind": 0.20, "thermal": 0.20, "air_quality": 0.15, "daylight": 0.10,
                 "travel": 0.10, "context": 0.05, "visibility": 0.05, "venue_fit": 0.05},
        wind_curve=curves.WIND_SENSITIVE, gust_max_kmh=50,
        base_advice=("Wear a helmet; use front and rear lights if any part of the ride is in low light.",),
        rationale=("Wet roads and gusty cross-winds are the main cycling hazards; rain reduces braking.",),
    ),
    Activity.golf: ActivityProfile(
        Activity.golf, "Golf", "Golf courses and driving ranges.",
        default_radius_km=25, max_radius_km=50, duration_min=240, strenuous=False, daylight="required",
        default_travel_mode="driving",
        weights={"wind": 0.25, "precipitation": 0.25, "thermal": 0.20, "uv": 0.10, "travel": 0.10,
                 "venue_fit": 0.05, "air_quality": 0.05},
        heat_curve=curves.HEAT_LIGHT, wind_curve=curves.WIND_SENSITIVE, gust_max_kmh=50, thunder_buffer_h=1,
        base_advice=("Check tee-time availability and course access with the club; membership may be required.",),
        rationale=("Golfers are exposed on open ground: any thunderstorm within an hour of the round excludes it.",),
    ),
    Activity.cricket: ActivityProfile(
        Activity.cricket, "Recreational cricket / practice", "Cricket grounds, large parks and recreation grounds.",
        default_radius_km=10, max_radius_km=30, duration_min=180, strenuous=True, daylight="required",
        default_travel_mode="driving",
        weights={"precipitation": 0.20, "surface": 0.10, "thermal": 0.25, "air_quality": 0.10, "travel": 0.15,
                 "wind": 0.05, "uv": 0.05, "venue_fit": 0.10},
        gust_max_kmh=55, prior_rain_hours=6,
        base_advice=("Bring plenty of water and shade for fielders and waiting batters.",),
        rationale=("Rain in the 6 hours before play can leave the outfield and pitch wet.",),
    ),
    Activity.football: ActivityProfile(
        Activity.football, "Outdoor football / five-a-side", "Football pitches and recreation grounds.",
        default_radius_km=10, max_radius_km=30, duration_min=90, strenuous=True, daylight="preferred",
        default_travel_mode="driving",
        weights={"thermal": 0.30, "air_quality": 0.20, "precipitation": 0.15, "surface": 0.05, "daylight": 0.10,
                 "travel": 0.15, "wind": 0.05, "venue_fit": 0.05},
        prior_rain_hours=3,
        base_advice=("Hydrate before kick-off and take water breaks every 20-25 minutes in warm weather.",),
        rationale=("High-intensity intermittent exercise: heat and air quality dominate.",),
    ),
    Activity.tennis: ActivityProfile(
        Activity.tennis, "Outdoor tennis", "Mapped outdoor tennis courts.",
        default_radius_km=10, max_radius_km=30, duration_min=90, strenuous=True, daylight="preferred",
        default_travel_mode="driving",
        weights={"wind": 0.25, "precipitation": 0.15, "surface": 0.10, "thermal": 0.20, "daylight": 0.10,
                 "travel": 0.15, "air_quality": 0.05, "venue_fit": 0.05},
        wind_curve=curves.WIND_SENSITIVE, gust_max_kmh=45, prior_rain_hours=3,
        base_advice=("Courts can be slippery after rain; check the surface before playing.",),
        rationale=("Wind affects ball flight strongly; wet courts are a slip hazard.",),
    ),
    Activity.hiking: ActivityProfile(
        Activity.hiking, "Hiking / nature walk", "Hiking routes, peaks, viewpoints, forts and nature reserves.",
        default_radius_km=30, max_radius_km=50, duration_min=240, strenuous=True, daylight="required",
        default_travel_mode="driving",
        weights={"precipitation": 0.25, "thermal": 0.20, "visibility": 0.10, "wind": 0.10, "air_quality": 0.10,
                 "travel": 0.15, "venue_fit": 0.05, "uv": 0.05},
        gust_max_kmh=50, thunder_buffer_h=1, end_before_sunset_min=60,
        base_advice=("Download an offline map, tell someone your route, and carry a torch and first-aid kit.",),
        rationale=("Hikes must finish well before sunset; heavy rain makes trails and waterfalls dangerous.",),
    ),
    Activity.picnic: ActivityProfile(
        Activity.picnic, "Picnic / park outing", "Picnic sites, parks and gardens.",
        default_radius_km=15, max_radius_km=40, duration_min=180, strenuous=False, daylight="required",
        default_travel_mode="driving",
        weights={"precipitation": 0.35, "thermal": 0.20, "uv": 0.10, "wind": 0.10, "air_quality": 0.10,
                 "context": 0.05, "travel": 0.10, "venue_fit": 0.05},
        heat_curve=curves.HEAT_LIGHT, gust_max_kmh=55,
        base_advice=("Pack a ground sheet, shade and waste bags; check park opening hours.",),
        rationale=("Rain is the main spoiler; shade and green cover improve comfort.",),
    ),
    Activity.outdoor_event: ActivityProfile(
        Activity.outdoor_event, "Outdoor event / gathering", "Large parks, recreation grounds and open venues.",
        default_radius_km=15, max_radius_km=40, duration_min=240, strenuous=False, daylight="preferred",
        default_travel_mode="driving",
        weights={"precipitation": 0.35, "wind": 0.20, "thermal": 0.20, "daylight": 0.10, "travel": 0.15,
                 "space": 0.10, "uv": 0.05},
        heat_curve=curves.HEAT_LIGHT, wind_curve=curves.WIND_SENSITIVE, gust_max_kmh=55,
        base_advice=("Confirm booking or permission with the venue owner; anchor tents and decorations.",),
        rationale=("Guests are exposed for hours: rain over the whole window and gusts (tents) matter most.",),
    ),
    Activity.photography: ActivityProfile(
        Activity.photography, "Outdoor photography", "Viewpoints, beaches, waterfronts, heritage sites and peaks.",
        default_radius_km=20, max_radius_km=50, duration_min=60, strenuous=False, daylight="golden_hour",
        default_travel_mode="driving",
        weights={"golden_hour": 0.25, "sky": 0.20, "visibility": 0.20, "precipitation": 0.20, "wind": 0.05,
                 "travel": 0.10, "venue_fit": 0.10},
        heat_curve=curves.HEAT_LIGHT, gust_max_kmh=62, heavy_rain_excludes=True,
        base_advice=("Arrive 20-30 minutes early to set up; carry a lens cloth in humid conditions.",),
        rationale=("Light quality (golden hour, partial cloud, clear air) matters more than temperature.",),
    ),
}


NATURE_WALK = ActivityProfile(
    Activity.hiking, "Nature walk", "Short walks in parks, gardens and nature reserves.",
    default_radius_km=5, max_radius_km=20, duration_min=60, strenuous=False, daylight="required",
    default_travel_mode="walking",
    weights={"thermal": 0.30, "air_quality": 0.25, "precipitation": 0.20, "travel": 0.10, "context": 0.10,
             "uv": 0.05, "venue_fit": 0.05},
    heat_curve=curves.HEAT_LIGHT, gust_max_kmh=55,
    base_advice=("Wear comfortable shoes and walk at a conversational pace.",),
    rationale=("A light-exertion variant of hiking: heat, air quality and calm green surroundings matter most.",),
)

WALK_WORDS = ("walk", "stroll")
HIKE_WORDS = ("hike", "hiking", "trek", "trail")


def profile_key(activity: Activity, detail: str | None) -> str:
    d = (detail or "").lower()
    if activity == Activity.hiking and any(w in d for w in WALK_WORDS) and not any(w in d for w in HIKE_WORDS):
        return "nature_walk"
    return activity.value


def get_profile(activity: Activity, detail: str | None = None) -> ActivityProfile:
    if profile_key(activity, detail) == "nature_walk":
        return NATURE_WALK
    return PROFILES[activity]


def photography_objective(detail: str | None, part_of_day: str | None) -> str:
    text = (detail or "").lower()
    if "sunrise" in text or part_of_day == "sunrise":
        return "sunrise"
    if "sunset" in text or part_of_day == "sunset" or "golden" in text:
        return "sunset"
    if "night" in text or "star" in text or "astro" in text or part_of_day == "night":
        return "night"
    return "general"

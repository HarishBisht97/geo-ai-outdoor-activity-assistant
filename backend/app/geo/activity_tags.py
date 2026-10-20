"""OpenStreetMap tag selectors per activity.

Each selector is an Overpass QL filter (without the spatial clause), the venue category it implies and
whether the tags *explicitly* indicate the activity or only make it plausible (`inferred`).
Generic area selectors (parks, recreation grounds) require a name when the search radius is large, to
keep payloads bounded and avoid thousands of tiny unnamed polygons.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.intent import Activity


@dataclass(frozen=True)
class TagSelector:
    ql: str
    category: str
    suitability: str  # explicit | inferred
    generic: bool = False  # generic areas: require a name for large radii, min area applies
    min_area_m2: float = 0.0
    note: str | None = None


def sport(name: str) -> str:
    return f'["sport"~"(^|;)({name})($|;)"]'


PARK = TagSelector('nwr["leisure"="park"]', "park", "explicit", generic=True)
GARDEN = TagSelector('nwr["leisure"="garden"]["access"!~"private|no"]', "garden", "inferred", generic=True)
NATURE_RESERVE = TagSelector('nwr["leisure"="nature_reserve"]', "nature_reserve", "explicit")
REC_GROUND = TagSelector('nwr["landuse"="recreation_ground"]', "recreation_ground", "inferred", generic=True,
                         min_area_m2=5000, note="Open recreation ground; activity facilities not mapped")
VIEWPOINT = TagSelector('nwr["tourism"="viewpoint"]', "viewpoint", "explicit")
PEAK = TagSelector('node["natural"="peak"]["name"]', "peak", "explicit")

ACTIVITY_SELECTORS: dict[str, list[TagSelector]] = {
    "nature_walk": [
        PARK,
        NATURE_RESERVE,
        GARDEN,
        TagSelector('nwr["leisure"="track"]["sport"!~"motor|horse"]', "running_track", "explicit"),
        TagSelector('nwr["tourism"="picnic_site"]', "picnic_site", "inferred"),
    ],
    Activity.running: [
        TagSelector('nwr["leisure"="track"]', "running_track", "explicit"),
        TagSelector('nwr["leisure"~"pitch|sports_centre|stadium"]' + sport("athletics|running"),
                    "athletics_track", "explicit"),
        PARK,
        NATURE_RESERVE,
        GARDEN,
    ],
    Activity.cycling: [
        TagSelector('way["highway"="cycleway"]["name"]', "cycleway", "explicit"),
        TagSelector('relation["route"="bicycle"]', "cycle_route", "explicit"),
        TagSelector('nwr["leisure"="park"]["bicycle"~"yes|designated|permissive"]', "park", "explicit"),
        TagSelector('nwr["leisure"="park"]', "park", "inferred", generic=True, min_area_m2=40000,
                    note="Large park; cycling permission not mapped"),
    ],
    Activity.golf: [
        TagSelector('nwr["leisure"="golf_course"]', "golf_course", "explicit"),
        TagSelector('nwr["golf"="driving_range"]', "driving_range", "explicit"),
    ],
    Activity.cricket: [
        TagSelector('nwr["leisure"~"pitch|sports_centre|stadium|recreation_ground"]' + sport("cricket"),
                    "cricket_ground", "explicit"),
        TagSelector('nwr["leisure"="park"]', "park", "inferred", generic=True, min_area_m2=10000,
                    note="Open park; cricket use is not mapped and may be restricted"),
        REC_GROUND,
    ],
    Activity.football: [
        TagSelector('nwr["leisure"~"pitch|sports_centre|stadium"]' + sport("soccer|football"),
                    "football_pitch", "explicit"),
        REC_GROUND,
    ],
    Activity.tennis: [
        TagSelector('nwr["leisure"~"pitch|sports_centre"]' + sport("tennis") + '["indoor"!="yes"]',
                    "tennis_court", "explicit"),
    ],
    Activity.hiking: [
        TagSelector('relation["route"="hiking"]', "hiking_route", "explicit"),
        PEAK,
        VIEWPOINT,
        NATURE_RESERVE,
        TagSelector('nwr["boundary"="protected_area"]["name"]', "protected_area", "inferred"),
        TagSelector('node["waterway"="waterfall"]["name"]', "waterfall", "explicit"),
        TagSelector('nwr["historic"~"fort|castle"]["name"]', "fort", "explicit"),
    ],
    Activity.picnic: [
        TagSelector('nwr["tourism"="picnic_site"]', "picnic_site", "explicit"),
        PARK,
        GARDEN,
    ],
    Activity.outdoor_event: [
        TagSelector('nwr["leisure"="park"]', "park", "inferred", generic=True, min_area_m2=5000,
                    note="Public park; event permission and booking not mapped"),
        REC_GROUND,
        TagSelector('nwr["leisure"="common"]', "common", "inferred", generic=True),
        TagSelector('nwr["amenity"="events_venue"][!"building"]', "events_venue", "explicit"),
    ],
    Activity.photography: [
        VIEWPOINT,
        TagSelector('nwr["natural"="beach"]', "beach", "explicit"),
        PEAK,
        TagSelector('nwr["historic"~"fort|monument|castle|ruins|memorial"]["name"]', "heritage", "explicit"),
        TagSelector('nwr["man_made"="pier"]', "pier", "explicit"),
        TagSelector('nwr["natural"="water"]["name"]', "lakeside", "inferred", note="Named water body; shoreline access not mapped"),
        PARK,
    ],
}

CATEGORY_LABELS = {
    "running_track": "running track",
    "athletics_track": "athletics track",
    "park": "park",
    "garden": "garden",
    "nature_reserve": "nature reserve",
    "recreation_ground": "recreation ground",
    "cycleway": "cycleway",
    "cycle_route": "cycle route",
    "golf_course": "golf course",
    "driving_range": "golf driving range",
    "cricket_ground": "cricket ground",
    "football_pitch": "football pitch",
    "tennis_court": "tennis court",
    "hiking_route": "hiking route",
    "peak": "peak",
    "viewpoint": "viewpoint",
    "protected_area": "protected area",
    "waterfall": "waterfall",
    "fort": "fort",
    "picnic_site": "picnic site",
    "common": "common",
    "events_venue": "outdoor events venue",
    "beach": "beach",
    "heritage": "heritage site",
    "pier": "pier",
    "lakeside": "lakeside",
    "commute_destination": "commute destination",
}

ALLOWED_TAGS = {
    "name", "name:en", "leisure", "sport", "access", "lit", "surface", "opening_hours", "fee", "covered",
    "indoor", "operator", "tourism", "natural", "historic", "route", "sac_scale", "website", "wheelchair",
    "ele", "landuse", "highway", "bicycle", "foot", "waterway", "distance", "description",
}

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import Coordinates


class Venue(BaseModel):
    id: str = Field(description="Stable id, e.g. 'osm:way:348082938'")
    name: str | None = Field(description="OSM name tag; null when unmapped (never invented)")
    display_label: str = Field(description="Name, or a deterministic descriptive label with the OSM id")
    coords: Coordinates
    osm_type: Literal["node", "way", "relation"]
    osm_id: int
    osm_url: str
    tags: dict[str, str] = Field(default_factory=dict, description="Allow-listed subset of OSM tags")
    category: str
    suitability: Literal["explicit", "inferred"]
    suitability_note: str | None = None
    area_m2: float | None = None
    distance_km: float = Field(description="Geodesic distance from the origin")
    elevation_m: float | None = None
    source_id: str

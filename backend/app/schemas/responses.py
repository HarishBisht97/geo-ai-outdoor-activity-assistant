from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import Coordinates, EvidenceValue, Provenance, SourceStatus, WarningItem
from app.schemas.intent import Activity, ExtractedIntent, GroupInfo, Preference, Sensitivity, TravelMode
from app.schemas.venue import Venue

ResponseStatus = Literal["ok", "needs_clarification", "no_suitable_option", "insufficient_data", "error"]
SlotStatus = Literal["suitable", "caution", "unverified", "excluded"]


class ResolvedPlace(Coordinates):
    label: str
    display_name: str | None = None
    source: Literal["nominatim", "user_coordinates"]
    source_id: str | None = None


class ResolvedWindow(BaseModel):
    start: datetime
    end: datetime
    timezone: str


class ResolvedIntent(BaseModel):
    activity: Activity
    activity_detail: str | None = None
    origin: ResolvedPlace
    destination: ResolvedPlace | None = None
    requested_venue_id: str | None = Field(
        default=None, description="Set when the named place is itself a suitable venue; it is evaluated first.")
    radius_km: float
    window: ResolvedWindow
    duration_minutes: int
    travel_mode: TravelMode
    sensitivities: list[Sensitivity] = Field(default_factory=list)
    group: GroupInfo = Field(default_factory=GroupInfo)
    preferences: list[Preference] = Field(default_factory=list)
    parser: Literal["slm", "rules_fallback"]
    assumptions: list[str] = Field(default_factory=list)


class ClarificationOption(BaseModel):
    field: str
    label: str
    value: dict[str, Any]


class Clarification(BaseModel):
    missing_fields: list[str]
    questions: list[str]
    options: list[ClarificationOption] = Field(default_factory=list)
    partial_intent: ExtractedIntent | None = None


class SlotConditions(BaseModel):
    temperature_c: EvidenceValue
    heat_index_c: EvidenceValue
    humidity_pct: EvidenceValue
    precip_probability_pct: EvidenceValue
    precip_mm: EvidenceValue
    prior_precip_mm: EvidenceValue
    wind_kmh: EvidenceValue
    gust_kmh: EvidenceValue
    wind_direction_deg: EvidenceValue
    cloud_cover_pct: EvidenceValue
    cloud_cover_low_pct: EvidenceValue
    visibility_m: EvidenceValue
    uv_index: EvidenceValue
    weather_code: EvidenceValue
    weather_description: str | None = None
    pm2_5: EvidenceValue
    pm10: EvidenceValue
    us_aqi: EvidenceValue
    daylight: bool | None = None
    sunrise: datetime | None = None
    sunset: datetime | None = None


class TravelInfo(BaseModel):
    mode: TravelMode
    straight_line_km: float
    route_distance_km: EvidenceValue
    duration_min: EvidenceValue
    note: str


class ContextIndicators(BaseModel):
    nearest_major_road_m: EvidenceValue
    nearest_major_road_class: str | None = None
    industrial_within_1km: bool | None = None
    green_share_500m: EvidenceValue
    nearest_water_m: EvidenceValue
    upwind_features: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    status: SourceStatus = "ok"
    note: str = (
        "Contextual indicators derived from OpenStreetMap features; not a pollution or traffic measurement."
    )


class ScoreComponent(BaseModel):
    name: str
    score: float | None = Field(description="0..1, null when evidence is missing")
    weight: float
    contribution: float = Field(description="Points contributed to the 0..100 total")
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str


class ScoreBreakdown(BaseModel):
    total: float = Field(ge=0, le=100)
    completeness: float = Field(ge=0, le=1)
    confidence: Literal["high", "medium", "low"]
    safety_margin: float = Field(description="0..1, distance from the nearest safety threshold")
    components: list[ScoreComponent]
    missing_policy: str = "Missing components are excluded and the total is reduced by 50% of their weight share."


class SlotResult(BaseModel):
    start: datetime
    end: datetime
    status: SlotStatus
    score: ScoreBreakdown | None
    conditions: SlotConditions
    exclusions: list[WarningItem] = Field(default_factory=list)
    cautions: list[WarningItem] = Field(default_factory=list)


class AlternativeSlot(BaseModel):
    start: datetime
    end: datetime
    status: SlotStatus
    total: float | None


class Reason(BaseModel):
    text: str
    fact_ids: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    rank: int
    venue: Venue
    best_slot: SlotResult
    alternative_slots: list[AlternativeSlot] = Field(default_factory=list)
    travel: TravelInfo | None = None
    context: ContextIndicators | None = None
    positives: list[Reason] = Field(default_factory=list)
    negatives: list[Reason] = Field(default_factory=list)
    advice: list[Reason] = Field(default_factory=list)
    warnings: list[WarningItem] = Field(default_factory=list)


class CandidateSummary(BaseModel):
    venue_id: str
    display_label: str
    coords: Coordinates
    category: str
    suitability: Literal["explicit", "inferred"]
    distance_km: float
    outcome: Literal["recommended", "ranked", "excluded", "unverified"]
    best_total: float | None = None
    reasons: list[str] = Field(default_factory=list)
    osm_url: str


class TimelineCell(BaseModel):
    total: float | None
    status: SlotStatus


class TimelineRow(BaseModel):
    venue_id: str
    label: str
    cells: list[TimelineCell]


class HourPoint(BaseModel):
    time: datetime
    temperature_c: float | None = None
    heat_index_c: float | None = None
    precip_probability_pct: float | None = None
    precip_mm: float | None = None
    wind_kmh: float | None = None
    gust_kmh: float | None = None
    cloud_cover_pct: float | None = None
    us_aqi: float | None = None
    pm2_5: float | None = None
    is_day: bool | None = None


class HourlySeries(BaseModel):
    venue_id: str
    label: str
    points: list[HourPoint]


class SunTimes(BaseModel):
    date: str
    sunrise: datetime | None
    sunset: datetime | None


class Timeline(BaseModel):
    slot_starts: list[datetime]
    rows: list[TimelineRow]
    series: list[HourlySeries]
    sun: list[SunTimes]


class Fact(BaseModel):
    id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    numbers: list[float] = Field(default_factory=list)


class NarrativeItem(BaseModel):
    text: str
    fact_ids: list[str] = Field(default_factory=list)


class Narrative(BaseModel):
    summary: NarrativeItem | None = None
    best: NarrativeItem | None = None
    alternative: NarrativeItem | None = None
    why: list[NarrativeItem] = Field(default_factory=list)
    carry: list[NarrativeItem] = Field(default_factory=list)
    watch_for: list[NarrativeItem] = Field(default_factory=list)
    postpone_if: list[NarrativeItem] = Field(default_factory=list)
    caveats: list[NarrativeItem] = Field(default_factory=list)
    source: Literal["slm", "template", "mixed"]
    removed_claims: int = 0
    notes: list[str] = Field(default_factory=list)


class ProviderStatus(BaseModel):
    provider: str
    purpose: str
    status: SourceStatus
    message: str | None = None


class ModelInfo(BaseModel):
    base_model: str
    base_revision: str
    runtime_repo: str | None = None
    quantization: str
    parameters: int
    loaded: bool


class RecommendResponse(BaseModel):
    request_id: str
    api_version: str
    engine_version: str
    rules_version: str
    model: ModelInfo
    status: ResponseStatus
    message: str
    generated_at: datetime
    reference_time: datetime
    data_mode: Literal["live", "fixture"]
    interpretation: ResolvedIntent | None = None
    extracted: ExtractedIntent | None = None
    clarification: Clarification | None = None
    recommendations: list[Recommendation] = Field(default_factory=list)
    candidates_considered: list[CandidateSummary] = Field(default_factory=list)
    timeline: Timeline | None = None
    facts: list[Fact] = Field(default_factory=list)
    narrative: Narrative | None = None
    warnings: list[WarningItem] = Field(default_factory=list)
    data_quality: list[ProviderStatus] = Field(default_factory=list)
    sources: list[Provenance] = Field(default_factory=list)
    attribution: list[str] = Field(default_factory=list)
    disclaimer: str
    timings_ms: dict[str, int] = Field(default_factory=dict)


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody

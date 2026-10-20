from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Activity(StrEnum):
    running = "running"
    cycling = "cycling"
    golf = "golf"
    cricket = "cricket"
    football = "football"
    tennis = "tennis"
    hiking = "hiking"
    picnic = "picnic"
    outdoor_event = "outdoor_event"
    photography = "photography"


SUPPORTED_ACTIVITIES = [a.value for a in Activity]

DayRef = Literal[
    "today",
    "tomorrow",
    "day_after_tomorrow",
    "this_weekend",
    "next_weekend",
    "weekday",
    "date",
    "next_n_days",
    "days_ahead",
    "unspecified",
]
PartOfDay = Literal[
    "early_morning",
    "morning",
    "midday",
    "afternoon",
    "evening",
    "sunrise",
    "sunset",
    "night",
    "after_work",
    "any",
]
Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
TravelMode = Literal["driving", "cycling", "walking"]
Sensitivity = Literal["respiratory", "heat_sensitive", "limited_mobility"]
Preference = Literal["shade", "water_view", "quiet", "lit", "low_traffic", "greenery", "large_space"]


class TimeExpression(BaseModel):
    day_ref: DayRef = "unspecified"
    weekday: Weekday | None = None
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    n_days: int | None = Field(default=None, ge=1, le=7)
    days_ahead: int | None = Field(default=None, ge=0, le=366, description="'in 10 days' -> 10")
    part_of_day: PartOfDay | None = None
    clock_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class GroupInfo(BaseModel):
    children: bool = False
    elderly: bool = False
    size: int | None = Field(default=None, ge=1, le=10000)


class ExtractedIntent(BaseModel):
    """What the SLM (or the rule-based fallback) extracts. Relative time only - never absolute timestamps."""

    activity: Activity | Literal["unsupported"] | None = None
    activity_detail: str | None = Field(default=None, max_length=80)
    location_text: str | None = Field(default=None, max_length=120)
    destination_text: str | None = Field(default=None, max_length=120)
    radius_km: float | None = Field(default=None, gt=0)
    duration_minutes: int | None = Field(default=None, ge=10, le=24 * 60)
    time: TimeExpression = Field(default_factory=TimeExpression)
    travel_mode: TravelMode | None = None
    group: GroupInfo = Field(default_factory=GroupInfo)
    sensitivities: list[Sensitivity] = Field(default_factory=list)
    preferences: list[Preference] = Field(default_factory=list)


class IntentOverrides(BaseModel):
    """Structured answers from the clarification UI. Any provided field wins over extraction."""

    activity: Activity | None = None
    activity_detail: str | None = Field(default=None, max_length=80)
    location_text: str | None = Field(default=None, max_length=120)
    destination_text: str | None = Field(default=None, max_length=120)
    time: TimeExpression | None = None
    duration_minutes: int | None = Field(default=None, ge=10, le=24 * 60)
    sensitivities: list[Sensitivity] | None = None
    group: GroupInfo | None = None

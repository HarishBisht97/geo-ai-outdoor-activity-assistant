from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.common import Coordinates
from app.schemas.intent import IntentOverrides, Sensitivity, TravelMode


class OriginInput(Coordinates):
    label: str | None = Field(default=None, max_length=120)


class TimeWindowInput(BaseModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _check(self) -> "TimeWindowInput":
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("time_window start/end must include a timezone offset")
        if self.end <= self.start:
            raise ValueError("time_window end must be after start")
        return self


class Preferences(BaseModel):
    radius_km: float | None = Field(default=None, gt=0, description="Search radius; clamped to server maximum")
    travel_mode: TravelMode | None = None
    max_results: int = Field(default=3, ge=1, le=5)
    origin: OriginInput | None = Field(
        default=None, description="Explicit origin (e.g. browser geolocation with user consent)"
    )
    time_window: TimeWindowInput | None = None
    sensitivities: list[Sensitivity] | None = None


class RecommendRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    preferences: Preferences = Field(default_factory=Preferences)
    overrides: IntentOverrides | None = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "question": "Where can I go running tomorrow morning near Powai?",
                    "preferences": {"radius_km": 10, "travel_mode": "driving"},
                }
            ]
        }
    }

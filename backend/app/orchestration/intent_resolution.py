"""Merge request preferences/overrides into the extracted intent and build clarification payloads."""

from __future__ import annotations

from app.ranking.activities import PROFILES
from app.schemas.intent import Activity, ExtractedIntent
from app.schemas.requests import RecommendRequest
from app.schemas.responses import Clarification, ClarificationOption
from app.services.geocoding import GeocodeResult


def apply_overrides(intent: ExtractedIntent, req: RecommendRequest) -> ExtractedIntent:
    out = intent.model_copy(deep=True)
    ov = req.overrides
    if ov:
        for f in ("activity", "activity_detail", "location_text", "destination_text", "time", "duration_minutes", "group"):
            val = getattr(ov, f)
            if val is not None:
                setattr(out, f, val)
        if ov.sensitivities is not None:
            out.sensitivities = list(ov.sensitivities)
    p = req.preferences
    if p.radius_km is not None:
        out.radius_km = p.radius_km
    if p.travel_mode is not None:
        out.travel_mode = p.travel_mode
    if p.sensitivities:
        out.sensitivities = list(dict.fromkeys([*out.sensitivities, *p.sensitivities]))
    return out


def activity_options() -> list[ClarificationOption]:
    return [ClarificationOption(field="activity", label=p.label, value={"activity": a.value}) for a, p in PROFILES.items()]


def missing_activity(intent: ExtractedIntent) -> Clarification:
    return Clarification(
        missing_fields=["activity"],
        questions=["Which outdoor activity are you planning?"],
        options=activity_options(),
        partial_intent=intent,
    )


def unsupported_activity(intent: ExtractedIntent) -> Clarification:
    what = intent.activity_detail or "That activity"
    return Clarification(
        missing_fields=["activity"],
        questions=[f"{what[:1].upper() + what[1:]} is not supported yet. Would one of the supported activities work instead?"],
        options=activity_options(),
        partial_intent=intent,
    )


def missing_location(intent: ExtractedIntent, need_location: bool, commute: bool, need_destination: bool) -> Clarification:
    fields, qs = [], []
    if need_location:
        fields.append("location")
        qs.append("Where are you starting from? A neighbourhood, landmark or city works (or share your location).")
    if need_destination:
        fields.append("destination")
        qs.append("Where are you cycling to?" if commute else "Where are you going?")
    return Clarification(missing_fields=fields, questions=qs, partial_intent=intent)


def location_options(field: str, query: str, results: list[GeocodeResult], intent: ExtractedIntent) -> Clarification:
    return Clarification(
        missing_fields=[field],
        questions=[f"'{query}' matches several places. Which one did you mean?"],
        options=[
            ClarificationOption(
                field=field,
                label=r.display_name[:120],
                value={"origin": {"lat": r.lat, "lon": r.lon, "label": r.label}} if field == "location"
                else {"destination_text": r.display_name[:120]},
            )
            for r in results
        ],
        partial_intent=intent,
    )


def location_not_found(field: str, query: str, intent: ExtractedIntent) -> Clarification:
    return Clarification(
        missing_fields=[field],
        questions=[f"I couldn't find '{query}' on OpenStreetMap. Could you give a nearby landmark, area or city name?"],
        partial_intent=intent,
    )


def time_clarification(intent: ExtractedIntent, message: str) -> Clarification:
    return Clarification(
        missing_fields=["time"],
        questions=[f"{message} Which day and time should I check?"],
        options=[
            ClarificationOption(field="time", label="Today", value={"time": {"day_ref": "today", "part_of_day": "any"}}),
            ClarificationOption(field="time", label="Tomorrow morning",
                                value={"time": {"day_ref": "tomorrow", "part_of_day": "morning"}}),
            ClarificationOption(field="time", label="Tomorrow evening",
                                value={"time": {"day_ref": "tomorrow", "part_of_day": "evening"}}),
            ClarificationOption(field="time", label="This weekend", value={"time": {"day_ref": "this_weekend"}}),
        ],
        partial_intent=intent,
    )


def is_commute(intent: ExtractedIntent) -> bool:
    return intent.activity == Activity.cycling and "commute" in (intent.activity_detail or "")

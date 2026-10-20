"""SLM stage 1: intent extraction with strict parsing and deterministic validation.

Pipeline: grammar-constrained JSON -> json.loads -> flat schema mapping -> Pydantic -> semantic checks
(location must appear in the question, activity cross-checked with keyword matching, ranges clamped).
Any failure falls back to the rule-based parser; the response records which parser was used.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from pydantic import ValidationError
from rapidfuzz import fuzz

from app.core.config import Settings
from app.core.errors import OverloadedError, SLMTimeoutError, SLMUnavailableError
from app.core.logging import log_event
from app.schemas.intent import Activity, ExtractedIntent, GroupInfo, TimeExpression
from app.slm import rule_parser
from app.slm.prompts import INTENT_SCHEMA, INTENT_SYSTEM, intent_user_prompt
from app.slm.runtime import TextGenerator

logger = logging.getLogger(__name__)


@dataclass
class IntentResult:
    intent: ExtractedIntent
    parser: str  # slm | rules_fallback
    notes: list[str] = field(default_factory=list)
    slm_error: str | None = None


def _none(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return None if v in ("", "none", "null", "None") else v


def flat_to_intent(d: dict) -> ExtractedIntent:
    """Map the SLM's flat JSON into the validated ExtractedIntent model (raises ValidationError)."""
    act = d.get("activity")
    clock = _none(d.get("clock_time"))
    if clock and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", clock):
        clock = None
    date = _none(d.get("date"))
    if date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        date = None
    n_days = d.get("n_days") or None
    day_ref = d.get("day_ref") or "unspecified"
    if day_ref == "date" and not date:
        day_ref = "unspecified"
    if day_ref in ("next_n_days", "days_ahead") and not n_days:
        day_ref = "unspecified"
    weekday = _none(d.get("weekday"))
    if day_ref == "weekday" and not weekday:
        day_ref = "unspecified"
    return ExtractedIntent(
        activity=None if act in (None, "none") else act,
        activity_detail=_none(d.get("activity_detail")),
        location_text=_none(d.get("location_text")),
        destination_text=_none(d.get("destination_text")),
        radius_km=float(d["radius_km"]) if d.get("radius_km") and d["radius_km"] > 0 else None,
        duration_minutes=int(d["duration_minutes"]) if d.get("duration_minutes") and 10 <= d["duration_minutes"] <= 1440 else None,
        time=TimeExpression(
            day_ref=day_ref,
            weekday=weekday if day_ref == "weekday" else None,
            date=date if day_ref == "date" else None,
            n_days=min(7, max(1, int(n_days))) if day_ref == "next_n_days" and n_days else None,
            days_ahead=min(366, max(0, int(n_days))) if day_ref == "days_ahead" and n_days else None,
            part_of_day=_none(d.get("part_of_day")),
            clock_time=clock,
        ),
        travel_mode=_none(d.get("travel_mode")),
        group=GroupInfo(children=bool(d.get("children")), elderly=bool(d.get("elderly"))),
        sensitivities=list(dict.fromkeys(d.get("sensitivities") or [])),
        preferences=list(dict.fromkeys(d.get("preferences") or [])),
    )


def location_in_question(location: str, question: str, threshold: int = 85) -> bool:
    return fuzz.partial_ratio(location.lower(), question.lower()) >= threshold


def reconcile(slm: ExtractedIntent, rules: ExtractedIntent, question: str) -> tuple[ExtractedIntent, list[str]]:
    """Deterministic validation of the SLM output against the question text and keyword evidence."""
    notes: list[str] = []
    out = slm.model_copy(deep=True)
    if out.location_text and not location_in_question(out.location_text, question):
        log_event(logger, "intent_location_rejected")
        notes.append("model_location_not_in_question")
        out.location_text = rules.location_text
    if not out.location_text and rules.location_text:
        out.location_text = rules.location_text
    if out.destination_text and not location_in_question(out.destination_text, question):
        out.destination_text = rules.destination_text
    if isinstance(rules.activity, Activity) and out.activity != rules.activity:
        notes.append(f"activity_keyword_override:{out.activity}->{rules.activity.value}")
        out.activity = rules.activity
        if rules.activity_detail and not out.activity_detail:
            out.activity_detail = rules.activity_detail
    if out.activity is None and rules.activity is not None:
        out.activity = rules.activity
    rules_walk = rules.activity == Activity.hiking and "walk" in (rules.activity_detail or "")
    if rules_walk and "walk" not in (out.activity_detail or ""):
        out.activity_detail = ", ".join(x for x in (rules.activity_detail, out.activity_detail) if x)
    # Rule day references come from explicit tokens ("saturday", "tomorrow", "2026-10-24"), so they win.
    day_fields = {"day_ref", "weekday", "date", "n_days", "days_ahead"}
    rules_day = rules.time.model_dump(include=day_fields)
    slm_day = out.time.model_dump(include=day_fields)
    if rules.time.day_ref != "unspecified" and rules_day != slm_day:
        if out.time.day_ref != "unspecified":
            notes.append(f"time_keyword_override:{out.time.day_ref}->{rules.time.day_ref}")
        out.time = rules.time.model_copy(update={"part_of_day": out.time.part_of_day or rules.time.part_of_day,
                                                 "clock_time": rules.time.clock_time or out.time.clock_time})
    elif rules.time.clock_time and out.time.clock_time != rules.time.clock_time:
        out.time.clock_time = rules.time.clock_time
    # Rule parts of day also come from literal words ("sunset", "after work", "morning").
    if rules.time.part_of_day and out.time.part_of_day != rules.time.part_of_day:
        if out.time.part_of_day is not None:
            notes.append(f"part_of_day_keyword_override:{out.time.part_of_day}->{rules.time.part_of_day}")
        out.time.part_of_day = rules.time.part_of_day
    if out.time.clock_time is None and rules.time.clock_time:
        out.time.clock_time = rules.time.clock_time
    if out.radius_km is None and rules.radius_km:
        out.radius_km = rules.radius_km
    out.sensitivities = list(dict.fromkeys([*out.sensitivities, *rules.sensitivities]))
    out.group = GroupInfo(children=out.group.children or rules.group.children,
                          elderly=out.group.elderly or rules.group.elderly)
    return out, notes


async def extract(slm: TextGenerator, question: str, settings: Settings) -> IntentResult:
    rules = rule_parser.parse(question)
    if not slm.is_loaded:
        return IntentResult(rules, "rules_fallback", ["slm_unavailable"], "model not loaded")
    try:
        res = await slm.generate_json(
            INTENT_SYSTEM, intent_user_prompt(question), INTENT_SCHEMA,
            max_tokens=settings.slm_intent_max_tokens, temperature=0.0, timeout_s=settings.slm_intent_timeout_s,
        )
        data = json.loads(res.text)
        if not isinstance(data, dict):
            raise ValueError("intent JSON is not an object")
        slm_intent = flat_to_intent(data)
    except (SLMUnavailableError, SLMTimeoutError, OverloadedError) as exc:
        return IntentResult(rules, "rules_fallback", ["slm_" + type(exc).__name__], str(exc))
    except (json.JSONDecodeError, ValueError, ValidationError, KeyError, TypeError) as exc:
        log_event(logger, "intent_parse_failed", logging.WARNING, error=type(exc).__name__)
        return IntentResult(rules, "rules_fallback", ["slm_invalid_output"], type(exc).__name__)
    merged, notes = reconcile(slm_intent, rules, question)
    return IntentResult(merged, "slm", notes)

"""Place x time evaluation and deterministic ranking.

Order of operations per (venue, slot): aggregate conditions -> safety filter -> (only if not excluded)
component scoring. Venues are then ranked by their best non-excluded, verified slot.

Tie-breaks (in order): total rounded to 0.5 desc, safety margin desc, travel time asc (unknown last),
distance asc, earlier slot, venue id.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.geo.spatial_context import NearbySource
from app.geo.wind_context import describe, upwind_sources
from app.ranking.activities import ActivityProfile
from app.ranking.conditions import SeriesIndex, aggregate
from app.ranking.safety import SafetyResult, UserProfile, evaluate
from app.ranking.scoring import ContextEvidence, TravelEvidence, adjusted_weights, combine, component_scores
from app.ranking.time_slots import Slot
from app.schemas.responses import ScoreBreakdown, SlotConditions
from app.schemas.venue import Venue


@dataclass
class VenueEvidence:
    venue: Venue
    weather: SeriesIndex
    air: SeriesIndex
    sun: dict[str, tuple[datetime | None, datetime | None]]
    travel: TravelEvidence | None
    context: ContextEvidence | None
    sources: list[NearbySource] = field(default_factory=list)


@dataclass
class EvaluatedSlot:
    slot: Slot
    cond: SlotConditions
    safety: SafetyResult
    score: ScoreBreakdown | None
    upwind: list[str]

    @property
    def status(self) -> str:
        return self.safety.status

    @property
    def total(self) -> float | None:
        return self.score.total if self.score else None


@dataclass
class VenueEvaluation:
    ev: VenueEvidence
    slots: list[EvaluatedSlot]
    best: EvaluatedSlot | None
    outcome: str  # ranked | excluded | unverified


RECOMMENDABLE = ("suitable", "caution")


def evaluate_venue(
    ev: VenueEvidence,
    slots: list[Slot],
    profile: ActivityProfile,
    user: UserProfile,
    objective: str,
    preferences: set[str],
    tz: ZoneInfo,
) -> VenueEvaluation:
    weights = adjusted_weights(profile, user)
    results: list[EvaluatedSlot] = []
    for slot in slots:
        day = slot.start.astimezone(tz).date().isoformat()
        sun = ev.sun.get(day, (None, None))
        cond = aggregate(slot, ev.weather, ev.air, sun, prior_hours=profile.prior_rain_hours or 6)
        up = upwind_sources(ev.sources, cond.wind_direction_deg.value, cond.wind_kmh.value)
        up_desc = [describe(s) for s in up]
        safety = evaluate(profile, slot, cond, ev.weather, ev.venue, user, objective, up_desc)
        score = None
        if safety.status != "excluded":
            comps = component_scores(profile, slot, cond, ev.venue, ev.travel, ev.context, user, objective, preferences)
            score = combine(comps, weights, safety.margin)
        results.append(EvaluatedSlot(slot, cond, safety, score, up_desc))

    def slot_key(s: EvaluatedSlot):
        return (-(s.total or 0), -s.safety.margin, s.slot.start)

    ok = sorted([s for s in results if s.status in RECOMMENDABLE], key=slot_key)
    unverified = sorted([s for s in results if s.status == "unverified"], key=slot_key)
    if ok:
        return VenueEvaluation(ev, results, ok[0], "ranked")
    if unverified:
        return VenueEvaluation(ev, results, unverified[0], "unverified")
    return VenueEvaluation(ev, results, None, "excluded")


def ranking_key(v: VenueEvaluation):
    b = v.best
    total = b.total if b and b.total is not None else 0.0
    travel = v.ev.travel.duration_min if v.ev.travel and v.ev.travel.duration_min is not None else math.inf
    return (
        -math.floor(total * 2 + 0.5) / 2,
        -(b.safety.margin if b else 0),
        travel,
        v.ev.venue.distance_km,
        b.slot.start if b else datetime.max.replace(tzinfo=ZoneInfo("UTC")),
        v.ev.venue.id,
    )


def rank(evaluations: list[VenueEvaluation]) -> tuple[list[VenueEvaluation], list[VenueEvaluation], list[VenueEvaluation]]:
    """Returns (ranked, unverified, excluded), each sorted deterministically."""
    ranked = sorted([v for v in evaluations if v.outcome == "ranked"], key=ranking_key)
    unverified = sorted([v for v in evaluations if v.outcome == "unverified"], key=ranking_key)
    excluded = sorted([v for v in evaluations if v.outcome == "excluded"], key=lambda v: (v.ev.venue.distance_km, v.ev.venue.id))
    return ranked, unverified, excluded


def alternative_slots(v: VenueEvaluation, k: int = 3, min_gap_h: int = 2) -> list[EvaluatedSlot]:
    if not v.best:
        return []
    pool = sorted([s for s in v.slots if s.status in RECOMMENDABLE and s is not v.best],
                  key=lambda s: (-(s.total or 0), s.slot.start))
    chosen: list[EvaluatedSlot] = []
    for s in pool:
        if all(abs(s.slot.start - c.slot.start) >= timedelta(hours=min_gap_h) for c in [v.best, *chosen]):
            chosen.append(s)
        if len(chosen) >= k:
            break
    return chosen


def summarize_exclusions(v: VenueEvaluation) -> list[str]:
    counts: dict[str, tuple[int, str]] = {}
    for s in v.slots:
        for e in s.safety.exclusions + (s.safety.gaps if s.safety.critical_gap else []):
            n, msg = counts.get(e.code, (0, e.message))
            counts[e.code] = (n + 1, msg)
    total = len(v.slots)
    return [f"{msg} ({n}/{total} slots)" for _, (n, msg) in sorted(counts.items(), key=lambda kv: -kv[1][0])][:3]

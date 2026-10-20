"""Deterministic narrative built only from facts. Used when the SLM is unavailable, times out, or when
validated SLM output leaves sections empty."""

from __future__ import annotations

from dataclasses import dataclass

from app.ranking.facts import RecFacts
from app.schemas.responses import Fact, Narrative, NarrativeItem, Reason


@dataclass
class RecSummary:
    prefix: str
    label: str
    slot_text: str
    status: str
    facts: RecFacts


def _item(r: Reason) -> NarrativeItem:
    return NarrativeItem(text=r.text, fact_ids=[f for f in r.fact_ids if f])


def template_narrative(recs: list[RecSummary], general: list[Fact], status: str, message: str,
                       requested_first: bool = False) -> Narrative:
    if not recs:
        caveats = [NarrativeItem(text=f.text, fact_ids=[f.id]) for f in general[:3]]
        return Narrative(summary=NarrativeItem(text=message, fact_ids=[f.id for f in general[:2]]), caveats=caveats,
                         source="template")
    r1 = recs[0]
    ids = r1.facts.ids
    summary = NarrativeItem(text=message, fact_ids=[ids["venue"], ids["slot"]])
    cond_ids = [ids[k] for k in ("heat", "rain", "air") if k in ids]
    if requested_first:
        best_text = (f"{r1.label} is the place you asked about; its best slot is {r1.slot_text} given the forecast "
                     "conditions listed.")
    elif status == "ok":
        best_text = (f"{r1.label} scores highest for this activity in the {r1.slot_text} slot given the forecast "
                     "conditions listed.")
    else:
        best_text = f"{r1.label}, {r1.slot_text}, is the best available option but could not be fully verified."
    best = NarrativeItem(text=best_text, fact_ids=[ids["venue"], ids["slot"], *cond_ids][:4])
    alternative = None
    if len(recs) > 1:
        r2 = recs[1]
        alternative = NarrativeItem(text=f"Alternative: {r2.label}, {r2.slot_text}.",
                                    fact_ids=[r2.facts.ids["venue"], r2.facts.ids["slot"]])
    why = [_item(r) for r in r1.facts.positives[:3]]
    caveats = [_item(r) for r in r1.facts.negatives[:2]]
    caveats += [NarrativeItem(text=f.text, fact_ids=[f.id]) for f in general[:2]]
    return Narrative(
        summary=summary,
        best=best,
        alternative=alternative,
        why=why,
        carry=[_item(r) for r in r1.facts.advice[:4]],
        watch_for=[_item(r) for r in r1.facts.watch_for[:3]],
        postpone_if=[_item(r) for r in r1.facts.postpone_if[:3]],
        caveats=caveats[:4],
        source="template",
    )

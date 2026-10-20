"""SLM stage 2: evidence-grounded explanation with claim validation and template fill-in."""

from __future__ import annotations

import json
import logging

from app.core.config import Settings
from app.core.errors import OverloadedError, SLMTimeoutError, SLMUnavailableError
from app.core.logging import log_event
from app.schemas.responses import Fact, Narrative
from app.slm.output_validator import ClaimValidator
from app.slm.prompts import EXPLAIN_SCHEMA, EXPLAIN_SYSTEM
from app.slm.runtime import TextGenerator

logger = logging.getLogger(__name__)
MIN_EXPLAIN_BUDGET_S = 10


def validate_explanation(data: dict, facts: list[Fact], question: str, prefixes: list[str],
                         template: Narrative, labels: dict[str, str] | None = None) -> Narrative:
    v = ClaimValidator(facts, question, prefixes, labels)
    summary = v.item(data.get("summary"), must_cite=prefixes[0] if prefixes else None)
    best = v.item(data.get("best"), require_prefix=prefixes[0] if prefixes else None)
    alternative = v.item(data.get("alternative"), require_prefix=prefixes[1]) if len(prefixes) > 1 else None
    if len(prefixes) <= 1 and isinstance(data.get("alternative"), dict) and data["alternative"].get("text"):
        v.report.removed += 1
    why = v.items(data.get("why"), 2)
    caveat = v.item(data.get("caveat"))
    filled = False

    def pick(slm_val, tpl_val):
        nonlocal filled
        if slm_val:
            return slm_val
        if tpl_val:
            filled = True
        return tpl_val

    data_caveats = [c for c in template.caveats if not caveat or c.text != caveat.text][:3]
    # carry / watch_for / postpone_if are always the engine's deterministic advice.
    narrative = Narrative(
        summary=pick(summary, template.summary),
        best=pick(best, template.best),
        alternative=pick(alternative, template.alternative),
        why=pick(why, template.why),
        carry=template.carry,
        watch_for=template.watch_for,
        postpone_if=template.postpone_if,
        caveats=([caveat] if caveat else []) + data_caveats,
        source="slm",
        removed_claims=v.report.removed,
    )
    if v.report.kept == 0:
        narrative.source = "template"
    elif filled or v.report.removed:
        narrative.source = "mixed"
    return narrative


async def explain(slm: TextGenerator, packet: str, facts: list[Fact], question: str, prefixes: list[str],
                  template: Narrative, settings: Settings, timeout_s: float | None = None,
                  labels: dict[str, str] | None = None) -> Narrative:
    budget = settings.slm_explain_timeout_s if timeout_s is None else min(timeout_s, settings.slm_explain_timeout_s)
    if not prefixes or not slm.is_loaded or budget < MIN_EXPLAIN_BUDGET_S:
        t = template.model_copy()
        reason = "language model not used" if budget >= MIN_EXPLAIN_BUDGET_S else "not enough time left"
        t.notes.append(f"Explanation generated from deterministic templates ({reason}).")
        return t
    try:
        res = await slm.generate_json(EXPLAIN_SYSTEM, packet, EXPLAIN_SCHEMA,
                                      max_tokens=settings.slm_explain_max_tokens, temperature=0.3,
                                      timeout_s=budget)
        data = json.loads(res.text)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (SLMUnavailableError, SLMTimeoutError, OverloadedError, json.JSONDecodeError, ValueError) as exc:
        log_event(logger, "explain_fallback", logging.WARNING, error=type(exc).__name__)
        t = template.model_copy()
        t.notes.append(f"Language-model explanation unavailable ({type(exc).__name__}); template text shown.")
        return t
    narrative = validate_explanation(data, facts, question, prefixes, template, labels)
    if narrative.removed_claims:
        narrative.notes.append(f"{narrative.removed_claims} generated statement(s) were removed because they were not "
                               "supported by the evidence.")
    return narrative

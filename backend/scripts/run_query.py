"""Run one live query through the full pipeline from the command line.

    python scripts/run_query.py "Where can I go running tomorrow morning near Powai?" [--json out.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache.ttl_cache import AsyncTTLCache  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.http import HttpClient  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.orchestration.recommendation_pipeline import Pipeline  # noqa: E402
from app.schemas.requests import RecommendRequest  # noqa: E402
from app.services.base import ServiceDeps  # noqa: E402
from app.slm.prompts import INTENT_SCHEMA, INTENT_SYSTEM, intent_user_prompt  # noqa: E402
from app.slm.runtime import DisabledRuntime, LlamaCppRuntime  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--radius", type=float)
    args = ap.parse_args()
    s = get_settings()
    configure_logging(s.log_level)
    http = HttpClient(s.user_agent, timeout_s=s.http_timeout_s, retries=s.http_retries)
    rt = LlamaCppRuntime(s) if s.slm_enabled else DisabledRuntime()
    if s.slm_enabled:
        rt.load()
        await rt.warmup(INTENT_SYSTEM, intent_user_prompt("Where can I go running tomorrow morning?"), INTENT_SCHEMA)
    pipe = Pipeline(s, ServiceDeps(s, http, AsyncTTLCache()), rt)
    req = RecommendRequest(question=args.question, preferences={"radius_km": args.radius} if args.radius else {})

    async def emit(ev, data):
        if ev == "stage":
            print(f"  .. {data['stage']}: {data.get('detail')}", file=sys.stderr)

    resp = await pipe.run(req, "cli", emit)
    await http.aclose()
    print(f"status={resp.status} timings={resp.timings_ms}")
    print("message:", resp.message)
    if resp.interpretation:
        i = resp.interpretation
        print(f"interpretation: {i.activity} detail={i.activity_detail} origin={i.origin.label} r={i.radius_km} "
              f"window={i.window.start}..{i.window.end} parser={i.parser}")
        for a in i.assumptions:
            print("  assumption:", a)
    if resp.clarification:
        print("clarification:", resp.clarification.questions, [o.label for o in resp.clarification.options][:4])
    for r in resp.recommendations:
        b = r.best_slot
        print(f"#{r.rank} {r.venue.display_label} [{r.venue.category}/{r.venue.suitability}] {r.venue.distance_km} km "
              f"slot={b.start}..{b.end} status={b.status} score={b.score.total if b.score else None}")
        for p in r.positives[:3]:
            print("   +", p.text)
        for n in r.negatives[:3]:
            print("   -", n.text)
        for w in r.warnings[:3]:
            print("   !", w.type, w.message)
    print("candidates:", [(c.display_label[:30], c.outcome, c.best_total) for c in resp.candidates_considered])
    print("data quality:", [(d.provider, d.status) for d in resp.data_quality])
    for w in resp.warnings:
        print("warning:", w.type, w.message)
    if resp.narrative:
        n = resp.narrative
        print(f"narrative source={n.source} removed={n.removed_claims}")
        print("  summary:", n.summary.text if n.summary else None)
        print("  best:", n.best.text if n.best else None)
        print("  alt:", n.alternative.text if n.alternative else None)
        for x in n.why:
            print("  why:", x.text, x.fact_ids)
        for x in n.carry:
            print("  carry:", x.text)
    if args.json:
        args.json.write_text(json.dumps(resp.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    asyncio.run(main())

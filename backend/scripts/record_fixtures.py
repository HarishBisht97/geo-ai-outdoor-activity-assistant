"""Record real provider exchanges for replay in tests.

Runs the deterministic pipeline (rule-based intent, no SLM) against the live APIs with generous
time budgets, so slow providers are captured rather than skipped, and writes
tests/fixtures/sessions/<name>.json.gz.

    python scripts/record_fixtures.py               # all scenarios
    python scripts/record_fixtures.py powai_running # one scenario

Recorded sessions are test data only. The API never serves them (fixture mode requires APP_ENV=test).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache.ttl_cache import AsyncTTLCache  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.http import HttpClient  # noqa: E402
from app.orchestration.recommendation_pipeline import Pipeline  # noqa: E402
from app.schemas.requests import RecommendRequest  # noqa: E402
from app.services.base import ServiceDeps  # noqa: E402
from app.slm.runtime import DisabledRuntime  # noqa: E402
from tests.support.transports import RecordingTransport, Session  # noqa: E402

SCENARIOS: dict[str, dict] = {
    "powai_running": {"question": "Where can I go running tomorrow morning near Powai?"},
    "whitefield_cricket": {"question": "Where can we play cricket this weekend near Whitefield?"},
    "cubbon_picnic": {"question": "Is Saturday afternoon good for a picnic in Cubbon Park with kids?"},
    "powai_running_200km": {"question": "Where can I go running within 200 km of Powai tomorrow morning?"},
}

RECORDING_SETTINGS = {
    "app_env": "test",
    "slm_enabled": False,
    "places_hedge_after_s": 60,
    "places_prefer_overpass_s": 90,
    "overpass_budget_s": 90,
    "overpass_timeout_s": 60,
    "overpass_context_budget_s": 60,
    "context_soft_wait_s": 60,
    "request_timeout_s": 300,
}


async def record(name: str, spec: dict) -> None:
    settings = Settings(**RECORDING_SETTINGS)
    transport = RecordingTransport()
    http = HttpClient(settings.user_agent, timeout_s=settings.http_timeout_s, retries=settings.http_retries,
                      transport=transport)
    recorded_at = datetime.now(UTC)
    pipe = Pipeline(settings, ServiceDeps(settings, http, AsyncTTLCache()), DisabledRuntime(),
                    clock=lambda: recorded_at)
    req = {"question": spec["question"], **({"preferences": spec["preferences"]} if "preferences" in spec else {})}
    resp = await pipe.run(RecommendRequest(**req), f"record-{name}")
    await http.aclose()
    session = Session(name, spec["question"], recorded_at, req, transport.exchanges)
    path = session.save()
    sources = ", ".join(f"{p.id}={p.status}" for p in resp.sources)
    print(f"{name}: status={resp.status} exchanges={len(transport.exchanges)} -> {path.name} "
          f"({path.stat().st_size // 1024} KB)\n  {resp.message}\n  {sources}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", default=list(SCENARIOS))
    args = ap.parse_args()
    for name in args.names:
        await record(name, SCENARIOS[name])


if __name__ == "__main__":
    asyncio.run(main())

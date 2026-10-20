from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import SLMTimeoutError
from app.main import create_app
from app.schemas.intent import ExtractedIntent
from app.services.open_meteo import coord_key
from app.slm import rule_parser
from app.slm.prompts import INTENT_SCHEMA
from app.slm.runtime import GenerationResult
from tests.support.transports import Override, ReplayTransport, Session

TEST_SETTINGS = {
    "app_env": "test",
    "log_level": "warning",
    "slm_enabled": False,
    "http_throttle": False,
    "http_retries": 0,
    # Same hedging as the recorder, so replay follows the recorded path; unrecorded requests fail instantly.
    "places_hedge_after_s": 30,
    "places_prefer_overpass_s": 30,
    "overpass_budget_s": 5,
    "overpass_context_budget_s": 5,
    "context_soft_wait_s": 5,
    "rate_limit_per_min": 1000,
    "allowed_origins": "http://localhost:5173",
}


def make_settings(**kw) -> Settings:
    return Settings(**{**TEST_SETTINGS, **kw})


# --------------------------------------------------------------------------- fake SLM
def intent_to_flat(i: ExtractedIntent) -> dict:
    t = i.time
    n_days = t.n_days or (t.days_ahead if t.day_ref == "days_ahead" else None) or 0
    return {
        "activity": (i.activity.value if hasattr(i.activity, "value") else i.activity) or "none",
        "activity_detail": i.activity_detail or "", "location_text": i.location_text or "",
        "destination_text": i.destination_text or "", "radius_km": int(i.radius_km or 0),
        "duration_minutes": i.duration_minutes or 0, "day_ref": t.day_ref, "weekday": t.weekday or "none",
        "date": t.date or "", "n_days": n_days, "part_of_day": t.part_of_day or "none",
        "clock_time": t.clock_time or "", "travel_mode": i.travel_mode or "none", "children": i.group.children,
        "elderly": i.group.elderly, "sensitivities": list(i.sensitivities), "preferences": list(i.preferences),
    }


def question_from_prompt(user: str) -> str:
    return re.findall(r"Question: (.*)\nJSON:", user)[-1]


def packet_options(packet: str) -> dict[str, tuple[str, list[str]]]:
    """{'R1': (label, [fact lines...])} parsed from the evidence packet."""
    out: dict[str, tuple[str, list[str]]] = {}
    current = None
    for line in packet.splitlines():
        m = re.match(r"^(R\d+) = (.+?) \((\w+)\), ", line)
        if m:
            current = m.group(1)
            out[current] = (m.group(2), [])
            continue
        m = re.match(r"^\s+(R\d+F\d+): (.*)$", line)
        if m and current:
            out[current][1].append(m.group(1))
    return out


def grounded_explanation(packet: str) -> dict:
    opts = packet_options(packet)
    label1, f1 = opts["R1"]
    out = {
        "summary": {"text": f"{label1} is the top option for this window.", "facts": f1[:2]},
        "best": {"text": "R1 offers the best balance of conditions in its slot.", "facts": f1[:3]},
        "alternative": {"text": "", "facts": []},
        "why": [{"text": "Forecast conditions in the chosen slot are within the safety limits.", "facts": f1[3:5]}],
        "caveat": {"text": "Conditions on site can differ from the forecast.", "facts": []},
    }
    if "R2" in opts:
        label2, f2 = opts["R2"]
        out["alternative"] = {"text": f"{label2} is a close alternative.", "facts": f2[:2]}
    return out


class FakeSLM:
    """Scripted stand-in for the llama.cpp runtime.

    intent: "rules" (echo the rule parser as model output), "malformed", "timeout" or a callable(question) -> dict
    explain: "grounded", "malformed", "timeout" or a callable(packet) -> dict
    """

    def __init__(self, intent: str | Callable = "rules", explain: str | Callable = "grounded"):
        self.intent = intent
        self.explain = explain
        self.calls: list[str] = []

    is_loaded = True

    def info(self) -> dict[str, Any]:
        return {"loaded": True}

    async def generate_json(self, system, user, schema, *, max_tokens, temperature, timeout_s) -> GenerationResult:
        kind = "intent" if schema is INTENT_SCHEMA else "explain"
        self.calls.append(kind)
        behaviour = self.intent if kind == "intent" else self.explain
        if behaviour == "timeout":
            raise SLMTimeoutError("fake timeout")
        if behaviour == "malformed":
            text = '{"activity": "running", "location_text": '
        elif callable(behaviour):
            text = json.dumps(behaviour(question_from_prompt(user) if kind == "intent" else user))
        elif kind == "intent":
            text = json.dumps(intent_to_flat(rule_parser.parse(question_from_prompt(user))))
        else:
            text = json.dumps(grounded_explanation(user))
        return GenerationResult(text, 100, 50, 0.01, False)


# --------------------------------------------------------------------------- replay app
class Replay:
    def __init__(self, client: TestClient, transport: ReplayTransport, session: Session | None):
        self.client = client
        self.transport = transport
        self.session = session

    def ask(self, question: str | None = None, **body) -> dict:
        payload = {"question": question or self.session.question, **body}
        r = self.client.post("/api/v1/recommend", json=payload)
        assert r.status_code == 200, r.text
        return r.json()


@contextmanager
def replay_app(session_name: str | None, overrides: list[Override] | None = None, slm=None, **settings):
    session = Session.load(session_name) if session_name else None
    transport = ReplayTransport(session.exchanges if session else [], overrides)
    clock_at = session.recorded_at if session else None
    app = create_app(make_settings(**settings), transport=transport, slm=slm or FakeSLM(), data_mode="fixture",
                     clock=(lambda: clock_at) if clock_at else None)
    with TestClient(app) as client:
        yield Replay(client, transport, session)


@pytest.fixture
def replay():
    return replay_app


# --------------------------------------------------------------------------- mutations
def for_cell(lat: float, lon: float, step: float, fn: Callable[[dict], None]):
    """Mutation applying `fn` to the Open-Meteo location object(s) covering the given coordinate cell."""
    target = coord_key(lat, lon, step)

    def mutate(body, request):
        lats = request.url.params.get("latitude", "").split(",")
        lons = request.url.params.get("longitude", "").split(",")
        objs = body if isinstance(body, list) else [body]
        for la, lo, obj in zip(lats, lons, objs, strict=False):
            if coord_key(float(la), float(lo), step) == target:
                fn(obj)
        return body

    return mutate


def all_cells(fn: Callable[[dict], None]):
    def mutate(body, request):
        for obj in body if isinstance(body, list) else [body]:
            fn(obj)
        return body

    return mutate

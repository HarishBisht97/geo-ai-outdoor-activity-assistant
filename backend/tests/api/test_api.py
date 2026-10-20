from __future__ import annotations

import json

from tests.conftest import replay_app


def sse_events(text: str) -> list[tuple[str, dict]]:
    out, event = [], None
    for line in text.splitlines():
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and event:
            out.append((event, json.loads(line.split(":", 1)[1].strip())))
            event = None
    return out


def test_health_and_ready():
    with replay_app(None) as r:
        h = r.client.get("/health")
        assert h.status_code == 200 and h.json()["status"] == "ok"
        ready = r.client.get("/ready")
        assert ready.status_code == 200
        body = ready.json()
        assert body["ready"] is True and body["slm_enabled"] is False
        assert "load_error" not in body["model"]


def test_meta_endpoints():
    with replay_app(None) as r:
        acts = r.client.get("/api/v1/activities").json()
        assert len({a["activity"] for a in acts}) == 10
        srcs = r.client.get("/api/v1/sources").json()
        ids = {s["id"] for s in srcs}
        assert {"geocode:nominatim", "places:overpass", "weather:open-meteo", "air:open-meteo"} <= ids


def test_validation_error_envelope_and_request_id():
    with replay_app(None) as r:
        resp = r.client.post("/api/v1/recommend", json={"question": "x"}, headers={"X-Request-ID": "abc123def456"})
        assert resp.status_code == 422
        err = resp.json()["error"]
        assert err["code"] == "validation_error" and err["request_id"] == "abc123def456"
        assert resp.headers["X-Request-ID"] == "abc123def456"
        assert r.client.post("/api/v1/recommend", json={"question": "a" * 501}).status_code == 422
        assert r.client.post("/api/v1/recommend", json={}).status_code == 422


def test_unsafe_request_id_is_replaced():
    with replay_app(None) as r:
        resp = r.client.get("/health", headers={"X-Request-ID": "<script>"})
        assert resp.headers["X-Request-ID"] != "<script>"


def test_rate_limit_returns_429_with_retry_after():
    with replay_app(None, rate_limit_per_min=2) as r:
        q = {"question": "Where can I go running tomorrow?"}  # no location -> fast clarification, no network
        codes = [r.client.post("/api/v1/recommend", json=q).status_code for _ in range(3)]
        assert codes[:2] == [200, 200] and codes[2] == 429
        last = r.client.post("/api/v1/recommend", json=q)
        assert last.json()["error"]["code"] == "rate_limited" and "Retry-After" in last.headers


def test_cors_allowlist():
    def preflight(client, origin):
        return client.options("/api/v1/recommend", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type"})

    with replay_app(None, allowed_origins="http://localhost:5173,https://geoai.example.app") as r:
        ok = preflight(r.client, "https://geoai.example.app")
        assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "https://geoai.example.app"
        assert preflight(r.client, "https://evil.example").status_code == 400


def test_stream_emits_stages_ranking_and_done():
    with replay_app("powai_running") as r:
        resp = r.client.post("/api/v1/recommend/stream", json={"question": r.session.question})
        assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
        events = sse_events(resp.text)
        names = [e for e, _ in events]
        assert "stage" in names and names[-1] == "done"
        assert names.index("ranking") < names.index("done")
        done = events[-1][1]
        assert done["status"] in ("ok", "partial") and done["recommendations"]


def test_stream_error_event_for_clarification_is_still_done():
    with replay_app(None) as r:
        resp = r.client.post("/api/v1/recommend/stream", json={"question": "Where can I go running tomorrow?"})
        events = sse_events(resp.text)
        assert events[-1][0] == "done" and events[-1][1]["status"] == "needs_clarification"


def test_openapi_schema_is_frozen_shape():
    with replay_app(None) as r:
        spec = r.client.get("/openapi.json").json()
        paths = spec["paths"]
        assert {"/api/v1/recommend", "/api/v1/recommend/stream", "/health", "/ready"} <= set(paths)
        schemas = spec["components"]["schemas"]
        for name in ("RecommendRequest", "RecommendResponse", "ErrorResponse", "Recommendation", "Provenance"):
            assert name in schemas

"""The 17 required end-to-end cases, replayed from real recorded provider sessions.

Each test goes through the public HTTP API (`POST /api/v1/recommend`) with a frozen clock, the recorded
exchanges, a scripted FakeSLM, and (for failure modes) overrides derived from the recorded data.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.ranking.activities import PROFILES
from app.schemas.intent import Activity
from tests.conftest import FakeSLM, all_cells, for_cell, replay_app
from tests.support.transports import fail, mutate

IST = ZoneInfo("Asia/Kolkata")


def local(ts: str) -> datetime:
    return datetime.fromisoformat(ts).astimezone(IST)


def source_ids(resp: dict) -> set[str]:
    return {s["id"] for s in resp["sources"]}


def warning_codes(resp: dict) -> set[str]:
    return {w["code"] for w in resp["warnings"]}


# 1 ------------------------------------------------------------------------------------------
def test_01_normal_running_query():
    with replay_app("powai_running") as r:
        resp = r.ask()
        assert not r.transport.missed
    assert resp["status"] == "ok"
    assert resp["data_mode"] == "fixture"
    it = resp["interpretation"]
    assert it["activity"] == "running" and it["parser"] == "slm"
    assert "Powai" in it["origin"]["label"]
    recs = resp["recommendations"]
    assert 1 <= len(recs) <= 3
    tomorrow = (resp["reference_time"] and local(resp["reference_time"]).date().toordinal() + 1)
    ids = source_ids(resp)
    for rec in recs:
        start, end = local(rec["best_slot"]["start"]), local(rec["best_slot"]["end"])
        assert start.date().toordinal() == tomorrow and start.hour >= 6 and end.hour <= 11
        assert rec["best_slot"]["status"] in ("suitable", "caution")
        assert rec["venue"]["osm_url"].startswith("https://www.openstreetmap.org/")
        assert rec["venue"]["source_id"] in ids
        for name, ev in rec["best_slot"]["conditions"].items():
            if isinstance(ev, dict) and "kind" in ev and ev.get("value") is not None:
                assert ev["source_id"] in ids, name
    for f in resp["facts"]:
        assert set(f["evidence_ids"]) <= ids | {"derived:engine"}, f
    assert {"weather:open-meteo", "air:open-meteo", "geocode:nominatim"} <= ids
    assert resp["narrative"]["source"] in ("slm", "mixed")
    assert any("OpenStreetMap" in a for a in resp["attribution"])


# 2 ------------------------------------------------------------------------------------------
def test_02_multi_day_weekend_cricket():
    with replay_app("whitefield_cricket") as r:
        resp = r.ask()
    assert resp["status"] == "ok"
    it = resp["interpretation"]
    assert it["activity"] == "cricket"
    start, end = local(it["window"]["start"]), local(it["window"]["end"])
    assert start.weekday() == 5 and end.weekday() == 6, (start, end)
    days = {local(t).date() for t in resp["timeline"]["slot_starts"]}
    assert len(days) == 2
    assert all(len(row["cells"]) == len(resp["timeline"]["slot_starts"]) for row in resp["timeline"]["rows"])
    assert len(resp["candidates_considered"]) >= 5
    for rec in resp["recommendations"]:
        assert local(rec["best_slot"]["start"]).weekday() in (5, 6)


# 3 ------------------------------------------------------------------------------------------
def test_03_asthma_stricter_air_quality():
    q = "I have asthma. Where can I go running tomorrow morning near Powai?"
    with replay_app("powai_running") as r:
        base = r.ask()
        resp = r.ask(q)
    assert "respiratory" in resp["interpretation"]["sensitivities"]
    assert resp["status"] in ("ok", "no_suitable_option", "insufficient_data")
    for rec in resp["recommendations"]:
        aqi = rec["best_slot"]["conditions"]["us_aqi"]["value"]
        assert aqi is None or aqi <= 100
        codes = {w["code"] for w in rec["warnings"]}
        assert codes & {"aqi_sensitive", "aqi_uncertainty", "air_missing"}
    # never more permissive than the default profile
    assert len(resp["recommendations"]) <= len(base["recommendations"])
    if resp["status"] == "no_suitable_option":
        assert "AQI" in resp["message"]


# 4 ------------------------------------------------------------------------------------------
def test_04_missing_location_asks_for_clarification():
    with replay_app(None) as r:
        resp = r.ask("Where can I go running tomorrow morning?")
        assert r.transport.requests == []
    assert resp["status"] == "needs_clarification"
    assert resp["clarification"]["missing_fields"] == ["location"]
    assert resp["recommendations"] == []


# 5 ------------------------------------------------------------------------------------------
def test_05_ambiguous_time_is_stated_as_assumption():
    with replay_app("powai_running") as r:
        resp = r.ask("Where can I go running near Powai?")
    assert resp["status"] == "ok"
    it = resp["interpretation"]
    assert any("time" in a.lower() or "hours" in a.lower() for a in it["assumptions"]), it["assumptions"]
    hours = (local(it["window"]["end"]) - local(it["window"]["start"])).total_seconds() / 3600
    assert 12 <= hours <= 48


# 6 ------------------------------------------------------------------------------------------
def test_06_zero_overpass_results():
    no_elements = mutate("overpass", lambda body, req: {**body, "elements": []})
    no_pois = mutate("nominatim", lambda body, req: [] if req.url.params.get("q", "").startswith("[") else body)
    with replay_app("powai_running", [no_elements, no_pois]) as r:
        resp = r.ask()
    assert resp["status"] == "no_suitable_option"
    assert resp["recommendations"] == []
    assert "No mapped places" in resp["message"]


# 7 ------------------------------------------------------------------------------------------
def test_07_weather_503_gives_insufficient_data():
    with replay_app("powai_running", [fail("api.open-meteo.com", 503, path="/v1/forecast")]) as r:
        resp = r.ask()
    assert resp["status"] == "insufficient_data"
    assert resp["recommendations"] == []
    assert "weather_missing" in warning_codes(resp)
    assert all(c["outcome"] == "unverified" for c in resp["candidates_considered"])


# 8 ------------------------------------------------------------------------------------------
def test_08_air_quality_nulls_are_a_data_gap():
    def null_air(obj):
        for k, v in obj.get("hourly", {}).items():
            if k != "time":
                obj["hourly"][k] = [None] * len(v)

    with replay_app("powai_running", [mutate("air-quality-api", all_cells(null_air))]) as r:
        resp = r.ask()
    assert resp["status"] == "ok"
    assert "air_missing" in warning_codes(resp)
    for rec in resp["recommendations"]:
        aqi = rec["best_slot"]["conditions"]["us_aqi"]
        assert aqi["value"] is None and aqi["kind"] == "unknown"
        assert any(c["name"] == "air_quality" and c["score"] is None for c in rec["best_slot"]["score"]["components"])


# 9 ------------------------------------------------------------------------------------------
def test_09_routing_failure_gives_partial_results():
    with replay_app("powai_running", [fail("routing.openstreetmap.de", 502), fail("router.project-osrm.org", 502)]) as r:
        resp = r.ask()
    assert resp["status"] == "ok"
    assert "routing_missing" in warning_codes(resp)
    for rec in resp["recommendations"]:
        assert rec["travel"]["duration_min"]["value"] is None
        assert rec["travel"]["straight_line_km"] is not None


# 10 -----------------------------------------------------------------------------------------
def test_10_beyond_forecast_horizon():
    with replay_app("powai_running") as r:
        resp = r.ask("Where can I go running near Powai in 10 days?")
    assert resp["status"] == "insufficient_data"
    assert resp["recommendations"] == []
    assert "forecast" in resp["message"].lower()


# 11 -----------------------------------------------------------------------------------------
def test_11_unsupported_activity():
    with replay_app(None) as r:
        resp = r.ask("Can I go skiing near Powai tomorrow?")
        assert r.transport.requests == []
    assert resp["status"] == "needs_clarification"
    assert resp["clarification"]["missing_fields"] == ["activity"]
    assert "not supported" in resp["clarification"]["questions"][0]
    assert {o["value"]["activity"] for o in resp["clarification"]["options"]} == {a.value for a in Activity}


# 12 -----------------------------------------------------------------------------------------
def test_12_malformed_model_json_falls_back():
    with replay_app("powai_running", slm=FakeSLM(intent="malformed", explain="malformed")) as r:
        resp = r.ask()
    assert resp["status"] == "ok"
    assert resp["interpretation"]["parser"] == "rules_fallback"
    assert "slm_fallback" in warning_codes(resp)
    assert resp["narrative"]["source"] == "template"
    assert resp["narrative"]["best"]["text"]


# 13 -----------------------------------------------------------------------------------------
def test_13_invented_venue_and_temperature_are_removed():
    def invented(packet: str) -> dict:
        return {
            "summary": {"text": "Marine Drive Promenade is the best place to run tomorrow.", "facts": ["R1F1"]},
            "best": {"text": "It will be a pleasant 35 C with a light breeze.", "facts": ["R1F4"]},
            "alternative": {"text": "R1 is also a good alternative.", "facts": ["R1F1"]},
            "why": [{"text": "Humid air makes running harder.", "facts": ["R1F4"]},
                    {"text": "R1 has the best conditions in the window.", "facts": ["R1F2"]}],
            "caveat": {"text": "Live traffic is light at this hour.", "facts": []},
        }

    with replay_app("powai_running", slm=FakeSLM(explain=invented)) as r:
        resp = r.ask()
    n = resp["narrative"]
    assert n["removed_claims"] >= 4
    text = " ".join(i["text"] for k in ("summary", "best", "alternative") if n[k] for i in [n[k]])
    text += " ".join(i["text"] for k in ("why", "caveats") for i in n[k])
    assert "Marine Drive" not in text and "35 C" not in text and "Live traffic" not in text
    assert resp["recommendations"][0]["venue"]["display_label"] in n["best"]["text"] + n["summary"]["text"] + text


# 14 -----------------------------------------------------------------------------------------
def test_14_unnamed_and_untagged_venues():
    def strip_names(body, req):
        for el in body.get("elements", []):
            if el.get("tags", {}).get("leisure") == "park":
                el["tags"].pop("name", None)
                el["tags"].pop("name:en", None)
        return body

    with replay_app("powai_running", [mutate("overpass", strip_names)]) as r:
        resp = r.ask()
    unnamed = [c for c in resp["candidates_considered"] if c["display_label"].startswith("Unnamed")]
    assert unnamed, "expected unnamed parks to be labelled by OSM id"
    for c in unnamed:
        assert "(OSM " in c["display_label"] and c["osm_url"]
    for rec in resp["recommendations"]:
        v = rec["venue"]
        assert v["name"] is None or v["name"] == v["tags"].get("name:en", v["tags"].get("name"))


# 15 -----------------------------------------------------------------------------------------
def test_15_near_ties_are_resolved_deterministically():
    with replay_app("powai_running") as r:
        a = r.ask()
    with replay_app("powai_running") as r:
        b = r.ask()
    order_a = [(c["venue_id"], c["best_total"]) for c in a["candidates_considered"]]
    order_b = [(c["venue_id"], c["best_total"]) for c in b["candidates_considered"]]
    assert order_a == order_b
    rounded = [round(c["best_total"] * 2) / 2 for c in a["candidates_considered"]
               if c["outcome"] in ("recommended", "ranked")]
    assert rounded == sorted(rounded, reverse=True)
    assert [r["rank"] for r in a["recommendations"]] == list(range(1, len(a["recommendations"]) + 1))


# 16 -----------------------------------------------------------------------------------------
def test_16_radius_200_km_is_clamped():
    limit = PROFILES[Activity.running].max_radius_km
    with replay_app("powai_running_200km") as r:
        resp = r.ask()
        via_prefs = r.ask("Where can I go running tomorrow morning near Powai?", preferences={"radius_km": 200})
    for out in (resp, via_prefs):
        assert out["status"] == "ok"
        assert out["interpretation"]["radius_km"] == limit
        assert any("exceeds" in a and "limit" in a for a in out["interpretation"]["assumptions"])
        assert all(c["distance_km"] <= limit for c in out["candidates_considered"])


# 17 -----------------------------------------------------------------------------------------
def test_17_thunderstorm_excludes_attractive_candidate():
    with replay_app("powai_running") as r:
        base = r.ask()
    top = base["recommendations"][0]["venue"]

    def thunder(obj):
        obj["hourly"]["weather_code"] = [95] * len(obj["hourly"]["weather_code"])

    storm = mutate("api.open-meteo.com", for_cell(top["coords"]["lat"], top["coords"]["lon"], 0.02, thunder),
                   path="/v1/forecast")
    with replay_app("powai_running", [storm]) as r:
        resp = r.ask()
    assert top["id"] not in {rec["venue"]["id"] for rec in resp["recommendations"]}
    cand = next(c for c in resp["candidates_considered"] if c["venue_id"] == top["id"])
    assert cand["outcome"] == "excluded"
    assert any("thunder" in reason.lower() for reason in cand["reasons"])

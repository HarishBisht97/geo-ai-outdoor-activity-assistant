from __future__ import annotations

from datetime import timedelta

import pytest

from app.ranking import curves
from app.ranking import thresholds as th
from app.ranking.activities import PROFILES, get_profile, profile_key
from app.ranking.ranker import evaluate_venue, rank, ranking_key
from app.ranking.safety import UserProfile
from app.ranking.scoring import combine
from app.ranking.time_slots import Slot, generate_slots
from app.schemas.intent import Activity
from app.utils.units import heat_index_c
from tests.unit.factories import IST, evidence, local, series, venue

RUN = PROFILES[Activity.running]


def morning_slots():
    return generate_slots([(local(6), local(11))], RUN.duration_min, None)


def run_eval(ev, user=None, profile=RUN, slots=None):
    return evaluate_venue(ev, slots or morning_slots(), profile, user or UserProfile(), "general", set(), IST)


def hour_index(dt):
    from tests.unit.factories import T0
    return int((dt - T0).total_seconds() // 3600)


# --------------------------------------------------------------------------- curves / units
def test_interp_clamps_and_interpolates():
    c = ((0, 1.0), (10, 0.0))
    assert curves.interp(c, -5) == 1.0
    assert curves.interp(c, 15) == 0.0
    assert curves.interp(c, 5) == pytest.approx(0.5)
    assert curves.interp(c, None) is None


@pytest.mark.parametrize("curve", [curves.HEAT_STRENUOUS, curves.AQI, curves.AQI_SENSITIVE, curves.UV])
def test_penalty_curves_are_monotonic_non_increasing(curve):
    xs = [curve[0][0] + i * (curve[-1][0] - curve[0][0]) / 50 for i in range(51)]
    ys = [curves.interp(curve, x) for x in xs]
    assert all(a >= b - 1e-9 for a, b in zip(ys, ys[1:], strict=False))


def test_heat_index_matches_nws_table():
    # NWS heat index chart: 32 C / 70% RH -> ~41 C; 30 C / 50% -> ~31 C; below 27 C it is ~ the air temperature
    assert heat_index_c(32, 70) == pytest.approx(41, abs=1.5)
    assert heat_index_c(30, 50) == pytest.approx(31, abs=1.0)
    assert heat_index_c(22, 50) == pytest.approx(22, abs=1.0)
    assert heat_index_c(None, 50) is None


# --------------------------------------------------------------------------- slots
def test_slots_on_the_hour_inside_window():
    slots = morning_slots()
    assert [s.start.hour for s in slots] == [6, 7, 8, 9, 10]
    assert all(s.end - s.start == timedelta(minutes=60) for s in slots)


def test_long_activity_still_overlaps_short_window():
    slots = generate_slots([(local(6), local(9))], 240, None)
    assert slots and all(s.start < local(9) for s in slots)


def test_slots_respect_forecast_coverage():
    slots = generate_slots([(local(6), local(11))], 60, coverage_end=local(8))
    assert max(s.end for s in slots) <= local(9)


# --------------------------------------------------------------------------- safety filters
def test_benign_conditions_are_suitable():
    v = run_eval(evidence())
    assert v.outcome == "ranked" and v.best.status == "suitable"
    assert v.best.score.total > 70


def test_thunderstorm_excludes_slot_and_neighbours_by_buffer():
    i = hour_index(local(8))
    w = series(overrides={"weather_code": {i: 95}})
    v = run_eval(evidence(weather=w))
    by_hour = {s.slot.start.astimezone(IST).hour: s for s in v.slots}
    assert by_hour[8].status == "excluded"
    assert any(e.code == "thunderstorm" for e in by_hour[8].safety.exclusions)
    assert by_hour[6].status != "excluded"


def test_thunder_everywhere_excludes_venue():
    v = run_eval(evidence(weather=series({"weather_code": 95})))
    assert v.outcome == "excluded" and v.best is None


def test_heat_index_danger_excludes_strenuous_only():
    hot = series({"temperature_2m": 35.0, "relative_humidity_2m": 55.0})  # heat index ~43 C
    assert run_eval(evidence(weather=hot)).outcome == "excluded"
    picnic = PROFILES[Activity.picnic]
    slots = generate_slots([(local(13), local(17))], picnic.duration_min, None)
    out = run_eval(evidence(weather=hot), profile=picnic, slots=slots)
    assert out.outcome == "ranked" and any(c.code == "heat" for c in out.best.safety.cautions)


def test_heat_sensitive_users_have_lower_limits():
    warm = series({"temperature_2m": 31.0, "relative_humidity_2m": 55.0})  # heat index ~33-34 C
    assert run_eval(evidence(weather=warm)).outcome == "ranked"
    assert run_eval(evidence(weather=warm), user=UserProfile({"heat_sensitive"})).outcome == "excluded"


@pytest.mark.parametrize(("aqi", "default", "asthma"), [
    (40, "suitable", "caution"),  # sensitive users always get the regional-model uncertainty caution
    (80, "suitable", "caution"),
    (130, "caution", "excluded"),
    (170, "caution", "excluded"),
    (230, "excluded", "excluded"),
])
def test_aqi_thresholds(aqi, default, asthma):
    air = series({"us_aqi": float(aqi)}, air=True)
    d = run_eval(evidence(air=air))
    a = run_eval(evidence(air=air), user=UserProfile({"respiratory"}))
    assert (d.best.status if d.best else "excluded") == default
    assert (a.best.status if a.best else "excluded") == asthma


def test_missing_air_is_unknown_not_good_and_blocks_sensitive():
    air = series({"us_aqi": None, "pm2_5": None, "pm10": None}, air=True)
    d = run_eval(evidence(air=air))
    assert d.outcome == "ranked"
    comp = next(c for c in d.best.score.components if c.name == "air_quality")
    assert comp.score is None
    assert d.best.score.completeness < 1.0
    a = run_eval(evidence(air=air), user=UserProfile({"respiratory"}))
    assert a.outcome == "unverified"


def test_missing_weather_is_unverified():
    w = series({k: None for k in ("temperature_2m", "precipitation_probability", "precipitation", "apparent_temperature",
                                  "relative_humidity_2m", "weather_code")})
    v = run_eval(evidence(weather=w))
    assert v.outcome == "unverified"
    assert v.best.status == "unverified"


def test_gusts_over_activity_limit_exclude():
    v = run_eval(evidence(weather=series({"wind_gusts_10m": 70.0})))
    assert v.outcome == "excluded"


def test_heavy_rain_excludes():
    v = run_eval(evidence(weather=series({"precipitation": 6.0, "precipitation_probability": 90.0})))
    assert v.outcome == "excluded"


def test_hike_must_finish_before_sunset():
    hike = PROFILES[Activity.hiking]
    slots = generate_slots([(local(10), local(19))], hike.duration_min, None)
    v = run_eval(evidence(venue(category="viewpoint")), profile=hike, slots=slots)
    cutoff = local(17).replace(minute=11)  # sunset 18:11 minus 60 min
    late = [s for s in v.slots if s.slot.end > cutoff]
    assert late and all(s.status == "excluded" for s in late)
    assert v.best and v.best.slot.end <= cutoff


# --------------------------------------------------------------------------- scoring
def test_completeness_penalty():
    full = combine([("a", 1.0, [], ""), ("b", 1.0, [], "")], {"a": 0.5, "b": 0.5}, 1.0)
    half = combine([("a", 1.0, [], ""), ("b", None, [], "")], {"a": 0.5, "b": 0.5}, 1.0)
    assert full.total == pytest.approx(100)
    assert half.total == pytest.approx(75)  # 100 x (1 - 0.5 x 0.5)
    assert half.completeness == pytest.approx(0.5)
    assert full.confidence == "high" and half.confidence == "low"


def test_profiles_cover_all_activities_and_breakdown_weights_are_normalised():
    assert set(PROFILES) == set(Activity)
    for p in PROFILES.values():
        assert all(w > 0 for w in p.weights.values()), p.label
    v = run_eval(evidence())
    assert sum(c.weight for c in v.best.score.components) == pytest.approx(1.0, abs=0.01)
    assert profile_key(Activity.hiking, "evening walk") == "nature_walk"
    assert get_profile(Activity.hiking, "walk").label == "Nature walk"


# --------------------------------------------------------------------------- ranking
def test_rank_is_deterministic_and_tie_breaks_by_margin_travel_distance_id():
    evs = [
        evidence(venue("osm:way:3", "C", distance_km=2.0), travel_min=10),
        evidence(venue("osm:way:2", "B", distance_km=1.0), travel_min=10),
        evidence(venue("osm:way:1", "A", distance_km=1.0), travel_min=10),
        evidence(venue("osm:way:4", "D", distance_km=0.5), travel_min=None),
    ]
    evals = [run_eval(e) for e in evs]
    totals = {round(v.best.score.total * 2) / 2 for v in evals}
    ranked, _, _ = rank(evals)
    ids = [v.ev.venue.id for v in ranked]
    if len(totals) == 1:
        # equal totals and margins: shorter known travel first, then distance, then id; unknown travel last
        assert ids[-1] == "osm:way:4"
        assert ids.index("osm:way:1") < ids.index("osm:way:2") < ids.index("osm:way:3")
    assert ids == [v.ev.venue.id for v in rank(list(reversed(evals)))[0]]
    assert [ranking_key(v) for v in ranked] == sorted(ranking_key(v) for v in ranked)


def test_better_conditions_outrank_closer_venue():
    rainy = series({"precipitation_probability": 80.0, "precipitation": 1.0})
    near = run_eval(evidence(venue("osm:way:1", "Near", distance_km=0.3), weather=rainy, travel_min=4))
    far = run_eval(evidence(venue("osm:way:2", "Far", distance_km=3.0), travel_min=25))
    ranked, _, _ = rank([near, far])
    assert ranked[0].ev.venue.name == "Far"


def test_safety_runs_before_scoring_excluded_slots_have_no_score():
    i = hour_index(local(7))
    v = run_eval(evidence(weather=series(overrides={"weather_code": {i: 95}})))
    for s in v.slots:
        if s.status == "excluded":
            assert s.score is None


def test_exclusion_constants_match_cited_sources():
    assert th.AQI_USG == 101 and th.AQI_UNHEALTHY == 151 and th.AQI_VERY_UNHEALTHY == 201
    assert th.HEAT_INDEX_CAUTION_C == 27 and th.HEAT_INDEX_EXTREME_CAUTION_C == 32
    assert th.HEAT_INDEX_DANGER_C == 41 and th.HEAT_INDEX_EXTREME_DANGER_C == 46


def test_slot_type():
    s = Slot(local(6), local(7))
    assert s.end > s.start

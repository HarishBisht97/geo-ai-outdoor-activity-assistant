from __future__ import annotations

import pytest

from app.schemas.intent import Activity
from app.schemas.responses import Fact, Narrative, NarrativeItem
from app.slm import rule_parser
from app.slm.intent_parser import flat_to_intent, location_in_question, reconcile
from app.slm.output_validator import ClaimValidator, _numbers
from app.slm.response_generator import validate_explanation
from scripts.eval_intent import eval_rules, load_cases

FACTS = [
    Fact(id="R1F1", text="Hiranandani Gardens park: heat index 29 C at 07:00, rain probability 10%"),
    Fact(id="R1F2", text="Travel about 12 min by car, 4.1 km"),
    Fact(id="R1F3", text="Nearest major road 350 m (primary); wind 12 km/h from the W"),
    Fact(id="R2F1", text="Powai Lake promenade: heat index 31 C, US AQI 85 (moderate)"),
    Fact(id="G1", text="Air quality is a regional model estimate (CAMS)"),
]
QUESTION = "Where can I go running tomorrow morning near Powai?"
LABELS = {"R1": "Hiranandani Gardens", "R2": "Powai Lake promenade"}


def validator():
    return ClaimValidator(FACTS, QUESTION, ["R1", "R2"], LABELS)


# --------------------------------------------------------------------------- rule parser
@pytest.mark.parametrize(("q", "activity", "loc", "day", "part", "clock"), [
    ("Where can I go running tomorrow morning near Powai?", Activity.running, "Powai", "tomorrow", "morning", None),
    ("Is Saturday afternoon good for cricket in Whitefield?", Activity.cricket, "Whitefield", "weekday",
     "afternoon", None),
    ("Cricket in Whitefield in 10 days?", Activity.cricket, "Whitefield", "days_ahead", None, None),
    ("tennis in Vasant Kunj on 2026-10-24 at 7 am", Activity.tennis, "Vasant Kunj", "date", None, "07:00"),
    ("Is it safe to cycle to work in Pune tomorrow at 8:30 pm?", Activity.cycling, "Pune", "tomorrow", None,
     "20:30"),
])
def test_rule_parser_examples(q, activity, loc, day, part, clock):
    i = rule_parser.parse(q)
    assert (i.activity, i.location_text, i.time.day_ref, i.time.part_of_day, i.time.clock_time) == (
        activity, loc, day, part, clock)


def test_rule_parser_never_invents_location_and_flags_unsupported():
    assert rule_parser.parse("Where can I go running tomorrow morning?").location_text is None
    assert rule_parser.parse("Can I go skiing near Manali tomorrow?").activity == "unsupported"
    i = rule_parser.parse("My elderly parents have asthma; walk near Bandra this evening")
    assert i.group.elderly and "respiratory" in i.sensitivities and i.activity == Activity.hiking


def test_rule_parser_floor_on_eval_set():
    m = eval_rules(load_cases())["metrics"]
    assert m["activity"] >= 0.95 and m["day_ref"] >= 0.95 and m["location"] >= 0.9


# --------------------------------------------------------------------------- flat mapping and reconciliation
def flat(**kw):
    base = {"activity": "running", "activity_detail": "", "location_text": "Powai", "destination_text": "",
            "radius_km": 0, "duration_minutes": 0, "day_ref": "tomorrow", "weekday": "none", "date": "", "n_days": 0,
            "part_of_day": "morning", "clock_time": "", "travel_mode": "none", "children": False, "elderly": False,
            "sensitivities": [], "preferences": []}
    return {**base, **kw}


def test_flat_to_intent_normalises_sentinels_and_inconsistent_fields():
    i = flat_to_intent(flat(clock_time="7am", date="tomorrow", day_ref="date"))
    assert i.time.clock_time is None and i.time.day_ref == "unspecified"
    assert flat_to_intent(flat(day_ref="days_ahead", n_days=10)).time.days_ahead == 10
    assert flat_to_intent(flat(day_ref="weekday")).time.day_ref == "unspecified"
    assert flat_to_intent(flat(activity="none")).activity is None
    assert flat_to_intent(flat(duration_minutes=5)).duration_minutes is None


def test_reconcile_rejects_hallucinated_location():
    q = "Where can I go running tomorrow morning?"
    out, notes = reconcile(flat_to_intent(flat(location_text="Mumbai")), rule_parser.parse(q), q)
    assert out.location_text is None and "model_location_not_in_question" in notes


def test_reconcile_keyword_activity_and_explicit_day_win():
    q = "Is Saturday afternoon good for cricket in Whitefield?"
    slm = flat_to_intent(flat(activity="football", location_text="Whitefield", day_ref="this_weekend",
                              part_of_day="afternoon"))
    out, notes = reconcile(slm, rule_parser.parse(q), q)
    assert out.activity == Activity.cricket
    assert out.time.day_ref == "weekday" and out.time.weekday == "saturday" and out.time.part_of_day == "afternoon"
    assert any(n.startswith("activity_keyword_override") for n in notes)
    assert any(n.startswith("time_keyword_override") for n in notes)


def test_reconcile_explicit_part_of_day_wins():
    q = "Where can I photograph the sunset near Mumbai tomorrow?"
    slm = flat_to_intent(flat(activity="photography", location_text="Mumbai", part_of_day="evening"))
    out, notes = reconcile(slm, rule_parser.parse(q), q)
    assert out.time.part_of_day == "sunset" and "part_of_day_keyword_override:evening->sunset" in notes


def test_reconcile_merges_sensitivities_from_rules():
    q = "I have asthma. Is it a good idea to run in Delhi tomorrow morning?"
    out, _ = reconcile(flat_to_intent(flat(location_text="Delhi")), rule_parser.parse(q), q)
    assert out.sensitivities == ["respiratory"]


def test_location_fuzzy_span():
    assert location_in_question("Koramangala", "running near koramangla tomorrow")
    assert not location_in_question("Andheri", "running near Powai tomorrow")


# --------------------------------------------------------------------------- claim validator
def test_numbers_with_units_and_clock():
    assert _numbers("29 C at 07:00, 12 km/h") == [(7.0, "clock"), (0.0, "clock"), (29.0, "C"), (12.0, "km/h")]


@pytest.mark.parametrize(("text", "facts", "ok"), [
    ("R1 has a heat index of 29 C and only a 10% chance of rain.", ["R1F1"], True),
    ("R1 has a heat index of 35 C.", ["R1F1"], False),                      # invented number
    ("R1 is 12 km away.", ["R1F2"], False),                                  # right number, wrong unit (min)
    ("R1 has a heat index of 31 C.", ["R1F1"], False),                       # number from an uncited fact
    ("Rain probability is 10%.", [], False),                                 # number without citation
    ("R1 is next to Phoenix Mall.", ["R1F1"], False),                        # invented name
    ("R1 will be humid.", ["R1F1"], False),                                  # unsupported condition
    ("R1 has little traffic nearby.", ["R1F3"], True),                       # 'major road' backs traffic
    ("R1 is the ideal place to run.", ["R1F1"], False),                      # banned superlative
    ("Live traffic is light on the way to R1.", ["R1F2"], False),            # banned claim
])
def test_claim_rules(text, facts, ok):
    item = validator().item({"text": text, "facts": facts})
    assert (item is not None) is ok


def test_render_replaces_option_ids_and_strips_fact_ids():
    item = validator().item({"text": "R1 (R1F1) stays cooler at 29 C.", "facts": ["R1F1"]})
    assert item.text == "Hiranandani Gardens stays cooler at 29 C."
    assert validator().item({"text": "R3 is closer.", "facts": ["R1F2"]}) is None


def test_best_must_cite_r1_only_and_duplicates_dropped():
    v = validator()
    assert v.item({"text": "Cooler at 29 C.", "facts": ["R1F1", "R2F1"]}, require_prefix="R1") is None
    assert v.item({"text": "Cooler at 29 C.", "facts": ["R1F1"]}, require_prefix="R1") is not None
    assert v.item({"text": "Cooler at 29 C.", "facts": ["R1F1"]}) is None


def test_validate_explanation_falls_back_per_section():
    tpl = Narrative(summary=NarrativeItem(text="T summary", fact_ids=[]), best=NarrativeItem(text="T best", fact_ids=[]),
                    alternative=None, why=[], carry=[NarrativeItem(text="Water", fact_ids=[])], watch_for=[],
                    postpone_if=[], caveats=[],
                    source="template")
    data = {"summary": {"text": "R1 is best tomorrow at 07:00.", "facts": ["R1F1"]},
            "best": {"text": "R1 is perfect.", "facts": ["R1F1"]},
            "alternative": {"text": "R2 is warmer at 31 C.", "facts": ["R2F1"]},
            "why": [{"text": "Only a 10% chance of rain.", "facts": ["R1F1"]}],
            "caveat": {"text": "Air quality is a regional model estimate.", "facts": ["G1"]}}
    n = validate_explanation(data, FACTS, QUESTION, ["R1", "R2"], tpl, LABELS)
    assert n.summary.text.startswith("Hiranandani Gardens")
    assert n.best.text == "T best"  # banned word -> template section
    assert n.alternative.text == "Powai Lake promenade is warmer at 31 C."
    assert [c.text for c in n.carry] == ["Water"]  # advice is always deterministic
    assert n.source == "mixed" and n.removed_claims == 1

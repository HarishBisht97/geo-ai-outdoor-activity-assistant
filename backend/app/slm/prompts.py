"""Prompts and grammar schemas for the two SLM stages. Kept byte-stable so llama.cpp can reuse the
cached prompt prefix across requests. Also exported to the Hugging Face model repo (hf_model/prompts/)."""

from __future__ import annotations

from app.schemas.intent import SUPPORTED_ACTIVITIES

PROMPT_VERSION = "2026-10-20.3"

INTENT_SYSTEM = f"""You convert a user's question about an outdoor activity into JSON. Extract only what the user said.
Rules:
- activity: one of {", ".join(SUPPORTED_ACTIVITIES)}; "unsupported" for any other activity; "none" if no activity is mentioned.
  Walking or strolling is "hiking" with activity_detail "walk". Parties, birthdays and gatherings are "outdoor_event".
- location_text: the place name exactly as written by the user, else "". Never invent or guess a place.
- destination_text: only for commuting (e.g. "cycle to Andheri"), else "".
- radius_km: integer if the user gave a distance, else 0. duration_minutes: integer if given, else 0.
- day_ref: today | tomorrow | day_after_tomorrow | this_weekend | next_weekend | weekday | date | next_n_days | days_ahead | unspecified.
  Use weekday (and set weekday) for a named day; next_n_days (and n_days) for "next two days"; days_ahead (and n_days) for
  "in 10 days"; date (YYYY-MM-DD) only for explicit dates.
- part_of_day: early_morning | morning | midday | afternoon | evening | sunrise | sunset | night | after_work | any | none.
- clock_time: "HH:MM" 24-hour if an exact time is given, else "".
- travel_mode: driving | cycling | walking | none.
- children / elderly: true only if the user mentions them.
- sensitivities: respiratory (asthma, breathing), heat_sensitive (pregnancy, heart condition), limited_mobility.
- preferences: shade, water_view, quiet, lit, low_traffic, greenery, large_space.
Do not compute dates. Output JSON only."""

INTENT_EXAMPLES = [
    ("Where can I go running tomorrow evening near Koregaon Park?",
     '{"activity":"running","activity_detail":"","location_text":"Koregaon Park","destination_text":"","radius_km":0,'
     '"duration_minutes":0,"day_ref":"tomorrow","weekday":"none","date":"","n_days":0,"part_of_day":"evening",'
     '"clock_time":"","travel_mode":"none","children":false,"elderly":false,"sensitivities":[],"preferences":[]}'),
    ("I have asthma. Any quiet place for a morning walk within 5 km of Powai over the next two days?",
     '{"activity":"hiking","activity_detail":"walk","location_text":"Powai","destination_text":"","radius_km":5,'
     '"duration_minutes":0,"day_ref":"next_n_days","weekday":"none","date":"","n_days":2,"part_of_day":"morning",'
     '"clock_time":"","travel_mode":"none","children":false,"elderly":false,"sensitivities":["respiratory"],'
     '"preferences":["quiet"]}'),
    ("Is it a good idea to cycle to work at 8 AM?",
     '{"activity":"cycling","activity_detail":"commute","location_text":"","destination_text":"","radius_km":0,'
     '"duration_minutes":0,"day_ref":"unspecified","weekday":"none","date":"","n_days":0,"part_of_day":"none",'
     '"clock_time":"08:00","travel_mode":"cycling","children":false,"elderly":false,"sensitivities":[],"preferences":[]}'),
    ("Birthday party for my kids on Sunday afternoon in Indiranagar, about 3 hours",
     '{"activity":"outdoor_event","activity_detail":"birthday party","location_text":"Indiranagar","destination_text":"",'
     '"radius_km":0,"duration_minutes":180,"day_ref":"weekday","weekday":"sunday","date":"","n_days":0,'
     '"part_of_day":"afternoon","clock_time":"","travel_mode":"none","children":true,"elderly":false,'
     '"sensitivities":[],"preferences":[]}'),
    ("Can we go skiing this weekend?",
     '{"activity":"unsupported","activity_detail":"skiing","location_text":"","destination_text":"","radius_km":0,'
     '"duration_minutes":0,"day_ref":"this_weekend","weekday":"none","date":"","n_days":0,"part_of_day":"none",'
     '"clock_time":"","travel_mode":"none","children":false,"elderly":false,"sensitivities":[],"preferences":[]}'),
]


def intent_user_prompt(question: str) -> str:
    shots = "\n\n".join(f"Question: {q}\nJSON: {a}" for q, a in INTENT_EXAMPLES)
    return f"{shots}\n\nQuestion: {question}\nJSON:"


def _enum(values: list[str]) -> dict:
    return {"type": "string", "enum": values}


INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "activity": _enum([*SUPPORTED_ACTIVITIES, "unsupported", "none"]),
        "activity_detail": {"type": "string"},
        "location_text": {"type": "string"},
        "destination_text": {"type": "string"},
        "radius_km": {"type": "integer"},
        "duration_minutes": {"type": "integer"},
        "day_ref": _enum(["today", "tomorrow", "day_after_tomorrow", "this_weekend", "next_weekend", "weekday", "date",
                          "next_n_days", "days_ahead", "unspecified"]),
        "weekday": _enum(["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "none"]),
        "date": {"type": "string"},
        "n_days": {"type": "integer"},
        "part_of_day": _enum(["early_morning", "morning", "midday", "afternoon", "evening", "sunrise", "sunset", "night",
                              "after_work", "any", "none"]),
        "clock_time": {"type": "string"},
        "travel_mode": _enum(["driving", "cycling", "walking", "none"]),
        "children": {"type": "boolean"},
        "elderly": {"type": "boolean"},
        "sensitivities": {"type": "array", "items": _enum(["respiratory", "heat_sensitive", "limited_mobility"]),
                          "maxItems": 3},
        "preferences": {"type": "array", "items": _enum(["shade", "water_view", "quiet", "lit", "low_traffic", "greenery",
                                                         "large_space"]), "maxItems": 4},
    },
    "required": ["activity", "activity_detail", "location_text", "destination_text", "radius_km", "duration_minutes",
                 "day_ref", "weekday", "date", "n_days", "part_of_day", "clock_time", "travel_mode", "children",
                 "elderly", "sensitivities", "preferences"],
}

EXPLAIN_SYSTEM = """You write a short, friendly explanation of outdoor activity recommendations that were already ranked by a deterministic engine.
Strict rules:
- Use ONLY the numbered facts provided. Every item must cite the fact ids it uses in "facts".
- Do not change the ranking: "best" describes option R1, "alternative" describes R2 (empty text if there is no R2).
- Copy numbers, place names and times exactly from the facts. Never add new numbers, places, sources or medical claims.
- Do not claim live traffic, measured pollution or certainty that the facts do not state.
- An option marked (caution) is usable with care: mention its main caution; never call it ideal or perfect.
- "why": the two most important reasons R1 was chosen. "caveat": the most important limitation or risk.
- Refer to places by their names. Put fact ids only in "facts", never in "text".
- Each section says something different; do not repeat a sentence across sections.
- Keep each text under 25 words. Output JSON only."""

# Text length and item counts are bounded in the grammar so the output always fits the token budget
# (about 6 items x 45 tokens); practical advice (carry / watch for / postpone) stays deterministic.
_ITEM = {"type": "object",
         "properties": {"text": {"type": "string", "maxLength": 200},
                        "facts": {"type": "array", "items": {"type": "string", "maxLength": 6}, "maxItems": 3}},
         "required": ["text", "facts"]}

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": _ITEM,
        "best": _ITEM,
        "alternative": _ITEM,
        "why": {"type": "array", "items": _ITEM, "maxItems": 2},
        "caveat": _ITEM,
    },
    "required": ["summary", "best", "alternative", "why", "caveat"],
}

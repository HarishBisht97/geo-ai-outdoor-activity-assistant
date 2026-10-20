"""Deterministic keyword/regex intent parser.

Used (a) as the fallback when the SLM is unavailable, times out or returns invalid output, and
(b) as a cross-check of the SLM's activity choice. It never guesses a location: if no location
phrase is found, location_text stays null and the pipeline asks the user.
"""

from __future__ import annotations

import re

from app.schemas.intent import Activity, ExtractedIntent, GroupInfo, TimeExpression

ACTIVITY_KEYWORDS: list[tuple[Activity, list[str]]] = [
    (Activity.photography, [r"photo\w*", r"camera", r"photoshoot", r"shoot (?:the )?(?:sunset|sunrise)"]),
    (Activity.golf, [r"golf\w*", r"tee time", r"driving range"]),
    (Activity.cricket, [r"cricket", r"nets practice"]),
    (Activity.football, [r"football", r"soccer", r"five[- ]a[- ]side", r"5[- ]a[- ]side", r"futsal"]),
    (Activity.tennis, [r"tennis"]),
    (Activity.hiking, [r"hik\w*", r"trek\w*", r"trail", r"nature walk", r"walk\w*", r"stroll\w*"]),
    (Activity.cycling, [r"cycl\w*", r"bik(?:e|ing)", r"bicycl\w*"]),
    (Activity.running, [r"run\b", r"running", r"jog\w*", r"sprint\w*", r"marathon"]),
    (Activity.picnic, [r"picnic\w*", r"park outing"]),
    (Activity.outdoor_event, [r"party", r"birthday", r"event", r"gathering", r"get[- ]together", r"celebrat\w*",
                              r"function", r"meet[- ]?up"]),
]
UNSUPPORTED = [r"ski\w*", r"swim\w*", r"surf\w*", r"kayak\w*", r"scuba", r"snorkel\w*", r"fishing", r"skydiv\w*",
               r"paraglid\w*", r"bowling", r"gym", r"badminton", r"basketball", r"volleyball", r"skating", r"boating",
               r"rafting", r"climb\w*", r"camping", r"horse riding"]

TIME_WORDS = (r"today|tonight|tomorrow|day after tomorrow|this weekend|next weekend|weekend|this evening|this morning|"
              r"morning|evening|afternoon|night|sunset|sunrise|after work|noon|midday|monday|tuesday|wednesday|"
              r"thursday|friday|saturday|sunday|over|for|at \d|on |next|within|during|between|by |with|this|"
              r"in the|before|after|around \d")
LOC_RE = re.compile(
    r"\b(?:near|around|in|at|close to|nearby|of|from|outside)\s+"
    r"(?!the\s+(?:morning|evening|afternoon|night|weekend)\b)"
    r"([A-Z][\w'.-]*(?:[\s,]+(?:[A-Z][\w'.-]*|de|da|ka|ki|nagar|road|park|hills?))*)"
)
WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "a couple of": 2, "couple of": 2}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
STOP_LOCATIONS = {"I", "Where", "What", "Is", "Can", "Should", "My", "The", "A", "Sunday", "Saturday", "Monday", "Tuesday",
                  "Wednesday", "Thursday", "Friday", "AM", "PM"}


def _has(pattern: str, text: str) -> bool:
    return re.search(rf"\b(?:{pattern})", text) is not None


def detect_activity(q: str) -> tuple[Activity | str | None, str | None]:
    low = q.lower()
    for act, pats in ACTIVITY_KEYWORDS:
        for p in pats:
            m = re.search(rf"\b{p}", low)
            if m:
                return act, m.group(0)
    for p in UNSUPPORTED:
        if re.search(rf"\b{p}", low):
            return "unsupported", re.search(rf"\b{p}", low).group(0)  # type: ignore[union-attr]
    return None, None


def detect_location(q: str) -> str | None:
    for m in LOC_RE.finditer(q):
        cand = m.group(1).strip(" ,.?!")
        parts = [p for p in re.split(r"\s+", cand) if p]
        while parts and parts[-1].lower().strip(",") in {"this", "tomorrow", "today", "on", "at", "in"}:
            parts.pop()
        cand = " ".join(parts).strip(" ,")
        if cand and cand.split()[0] not in STOP_LOCATIONS and len(cand) >= 3:
            return cand
    return None


def detect_time(q: str) -> TimeExpression:
    low = q.lower()
    t = TimeExpression()
    if "day after tomorrow" in low:
        t.day_ref = "day_after_tomorrow"
    elif "tomorrow" in low:
        t.day_ref = "tomorrow"
    elif re.search(r"\b(today|tonight|this (morning|evening|afternoon))\b", low):
        t.day_ref = "today"
    elif "next weekend" in low:
        t.day_ref = "next_weekend"
    elif "weekend" in low:
        t.day_ref = "this_weekend"
    else:
        m = re.search(r"\b(?:next|over the next|in the next|coming)\s+(\d+|one|two|three|four|five|six|seven|a couple of|couple of)\s+days\b", low)
        ahead = re.search(r"\b(?:in\s+(\d+)\s+days?|(\d+)\s+days?\s+(?:from now|from today|later|ahead))\b", low)
        if m:
            n = m.group(1)
            t.day_ref, t.n_days = "next_n_days", min(7, int(n) if n.isdigit() else WORD_NUM[n])
        elif ahead and int(ahead.group(1) or ahead.group(2)) <= 366:
            t.day_ref, t.days_ahead = "days_ahead", int(ahead.group(1) or ahead.group(2))
        else:
            for wd in WEEKDAYS:
                if re.search(rf"\b{wd}\b", low):
                    t.day_ref, t.weekday = "weekday", wd  # type: ignore[assignment]
                    break
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", low)
    if m:
        t.day_ref, t.date = "date", m.group(1)

    if "sunset" in low:
        t.part_of_day = "sunset"
    elif "sunrise" in low:
        t.part_of_day = "sunrise"
    elif "after work" in low or "after office" in low:
        t.part_of_day = "after_work"
    elif "early morning" in low:
        t.part_of_day = "early_morning"
    elif "morning" in low:
        t.part_of_day = "morning"
    elif "afternoon" in low:
        t.part_of_day = "afternoon"
    elif "evening" in low:
        t.part_of_day = "evening"
    elif "tonight" in low or re.search(r"\bnight\b", low):
        t.part_of_day = "night"
    elif "noon" in low or "midday" in low or "lunch" in low:
        t.part_of_day = "midday"

    m = re.search(r"\b(?:at|around|by)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", low)
    if m and (m.group(3) or m.group(2)):
        hh, mm = int(m.group(1)), int(m.group(2) or 0)
        mer = (m.group(3) or "").replace(".", "")
        if mer == "pm" and hh < 12:
            hh += 12
        if mer == "am" and hh == 12:
            hh = 0
        if 0 <= hh <= 23:
            t.clock_time = f"{hh:02d}:{mm:02d}"
    return t


def parse(question: str) -> ExtractedIntent:
    q = " ".join(question.split())
    low = q.lower()
    activity, matched = detect_activity(q)
    detail_bits = []
    if matched and activity == Activity.hiking:
        detail_bits.append(matched)
    if activity == Activity.photography:
        for w in ("sunset", "sunrise", "night", "golden hour"):
            if w in low:
                detail_bits.append(w)
    if activity == Activity.cycling and re.search(r"\b(to work|commute|to office|to the office)\b", low):
        detail_bits.append("commute")
    if re.search(r"\b(children|kids|child|kid's|children's)\b", low):
        detail_bits.append("children")
    if "birthday" in low:
        detail_bits.append("birthday party")

    radius = None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|kms|kilometres|kilometers)\b", low)
    if m:
        radius = float(m.group(1))

    sens: list[str] = []
    if re.search(r"\b(asthma\w*|copd|breathing|respiratory|lung|bronch\w*|allerg\w*)\b", low):
        sens.append("respiratory")
    if re.search(r"\b(heat[- ]sensitive|pregnan\w*|heart condition|cardiac)\b", low):
        sens.append("heat_sensitive")
    if re.search(r"\b(wheelchair|knee|mobility|walking aid|cane)\b", low):
        sens.append("limited_mobility")
    group = GroupInfo(
        children=bool(re.search(r"\b(children|kids|child|toddler|kid's|children's)\b", low)),
        elderly=bool(re.search(r"\b(elderly|old parents|senior|grandparents?|aged parents|older adults?)\b", low)),
    )

    mode = None
    if re.search(r"\b(on foot|walk(?:ing)? distance|walk there)\b", low):
        mode = "walking"
    elif re.search(r"\b(by car|drive|driving)\b", low):
        mode = "driving"
    elif activity == Activity.cycling:
        mode = "cycling"

    dur = None
    m = re.search(r"\bfor\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?)\b", low)
    if m:
        v = float(m.group(1))
        dur = int(v * 60) if m.group(2).startswith("h") else int(v)
        dur = max(10, min(dur, 720))

    prefs = []
    for word, pref in (("shade", "shade"), ("shady", "shade"), ("lake", "water_view"), ("sea", "water_view"),
                       ("water", "water_view"), ("beach", "water_view"), ("quiet", "quiet"), ("peaceful", "quiet"),
                       ("lit ", "lit"), ("floodlit", "lit"), ("green", "greenery"), ("trees", "greenery"),
                       ("big space", "large_space"), ("large", "large_space")):
        if re.search(rf"\b{word}", low) and pref not in prefs:
            prefs.append(pref)

    dest = None
    m = re.search(r"\bto\s+([A-Z][\w'.-]*(?:\s+[A-Z][\w'.-]*)*)", q)
    if activity == Activity.cycling and m and m.group(1) not in STOP_LOCATIONS:
        dest = m.group(1)

    return ExtractedIntent(
        activity=activity,  # type: ignore[arg-type]
        activity_detail=", ".join(dict.fromkeys(detail_bits)) or None,
        location_text=detect_location(q),
        destination_text=dest,
        radius_km=radius,
        duration_minutes=dur,
        time=detect_time(q),
        travel_mode=mode,  # type: ignore[arg-type]
        group=group,
        sensitivities=sens,  # type: ignore[arg-type]
        preferences=prefs,  # type: ignore[arg-type]
    )

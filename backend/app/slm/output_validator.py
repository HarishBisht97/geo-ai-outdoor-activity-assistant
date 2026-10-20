"""Claim validation for SLM explanations.

An item survives only if:
- every cited fact id exists (unknown ids are dropped; an item with no valid citation and any number is dropped)
- every number in its text matches (within tolerance, with the same unit when a unit is given) a number in
  one of its cited facts
- every capitalised word (other than sentence-initial words and a small vocabulary) occurs in the facts or
  the question - this blocks invented venues, places and sources
- every weather or context condition it names (humid, rain, haze, traffic...) appears in some fact
- it contains no banned claim (live traffic, guaranteed safety, medical claims, "ideal"/"perfect")
- it does not repeat an item already kept in another section
"best" must cite R1 facts only; "alternative" must cite R2 facts (dropped if there is no R2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.responses import Fact, NarrativeItem

ID_RE = re.compile(r"\b(?:R\d+F\d+|G\d+|R\d+)\b")
TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")
ALLOWED_CAPS = {
    "I", "AQI", "US", "UV", "PM2.5", "PM10", "CAMS", "OSM", "OpenStreetMap", "Open-Meteo", "OSRM", "NWS", "C", "WHO",
    "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    "Saturday", "Sunday", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    "AM", "PM", "N", "NE", "E", "SE", "S", "SW", "W", "NW", "Best", "Alternative", "Option", "R1", "R2", "R3",
}
BANNED = [
    r"live traffic", r"real[- ]time traffic", r"guarantee", r"100\s*% safe", r"completely safe", r"no risk",
    r"perfectly safe", r"safe for (?:your )?asthma", r"cure", r"diagnos", r"medical advice", r"measured pollution",
    r"pollution level(?:s)? (?:is|are) (?:low|zero)", r"\bideal\b", r"\bperfect(?:ly)?\b", r"\bflawless\b",
]
NUM_TOL_ABS = 0.6
NUM_TOL_REL = 0.03

# A claim that mentions a condition must be backed by a fact mentioning it (any of the evidence stems).
CONDITION_TERMS: list[tuple[str, tuple[str, ...]]] = [
    (r"\bhumid", ("humid",)),
    (r"\b(?:rain|shower|drizzle|wet)", ("rain", "precip", "shower", "drizzle")),
    (r"\b(?:thunder|lightning|storm)", ("thunder", "storm", "lightning")),
    (r"\b(?:snow|ice|icy|frost)", ("snow", "ice", "frost")),
    (r"\b(?:fog|mist|visibility)", ("fog", "visibility")),
    (r"\b(?:smog|haze|hazy|smoke|dust)", ("smog", "haze", "smoke", "dust")),
    (r"\b(?:cloud|overcast)", ("cloud", "overcast")),
    (r"\b(?:windy|wind|breez|gust)", ("wind", "gust")),
    (r"\b(?:hot|heat|warm|scorching)", ("heat", "temperature", "hot")),
    (r"\b(?:cold|chilly|cool)", ("temperature", "cold", "cool", "heat index")),
    (r"\b(?:traffic|congest)", ("major road",)),
    (r"\b(?:crowd|busy)", ("crowd", "busy")),
]


@dataclass
class ValidationReport:
    kept: int = 0
    removed: int = 0


UNIT_RE = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*(°\s*c\b|deg(?:rees?)?\s*c?\b|c\b|km/h|kmh|kph|%|mm\b|km\b|m\b|min(?:ute)?s?\b|h\b|hours?\b|"
    r"ug/m3|µg/m3)?", re.I)
UNIT_ALIASES = {"°c": "C", "c": "C", "deg": "C", "degc": "C", "degree": "C", "degrees": "C", "degreesc": "C",
                "degreec": "C", "km/h": "km/h", "kmh": "km/h", "kph": "km/h", "%": "%", "mm": "mm", "km": "km",
                "m": "m", "min": "min", "mins": "min", "minute": "min", "minutes": "min", "h": "h", "hour": "h",
                "hours": "h", "ug/m3": "ug/m3", "µg/m3": "ug/m3"}

Number = tuple[float, str | None]


def _numbers(text: str) -> list[Number]:
    """Numbers with their unit (None when unitless). Clock times contribute their hour and minute."""
    t = ID_RE.sub(" ", text)
    out: list[Number] = []
    for hh, mm in TIME_RE.findall(t):
        out += [(float(hh), "clock"), (float(mm), "clock")]
    t = TIME_RE.sub(" ", t).replace(",", "")
    for value, unit in UNIT_RE.findall(t):
        key = re.sub(r"\s", "", unit.lower()) if unit else None
        out.append((float(value), UNIT_ALIASES.get(key, key) if key else None))
    return out


def _num_ok(n: Number, allowed: list[Number]) -> bool:
    value, unit = n
    for a, a_unit in allowed:
        if unit and a_unit != unit and not (unit == "clock" or a_unit == "clock"):
            continue
        if abs(value - a) <= max(NUM_TOL_ABS, NUM_TOL_REL * abs(a)):
            return True
    return False


def _caps_ok(text: str, corpus: str) -> bool:
    sentences = re.split(r"(?<=[.!?])\s+", ID_RE.sub(" ", text).strip())
    low = corpus.lower()
    for s in sentences:
        words = re.findall(r"[A-Za-z][\w.'-]*", s)
        for i, w in enumerate(words):
            if i == 0 or not w[0].isupper():
                continue
            core = w.strip(".'-")
            if core in ALLOWED_CAPS or core.upper() in ALLOWED_CAPS or core.lower() in low:
                continue
            return False
    return True


def _conditions_ok(text: str, corpus_lower: str) -> bool:
    low = text.lower()
    for pattern, stems in CONDITION_TERMS:
        if re.search(pattern, low) and not any(s in corpus_lower for s in stems):
            return False
    return True


REC_REF_RE = re.compile(r"\(?\b(R\d+)\b(?!F)\)?")
FACT_REF_RE = re.compile(r"\s*[\[(]?\b(?:R\d+F\d+|G\d+)\b(?:\s*,\s*\b(?:R\d+F\d+|G\d+)\b)*[\])]?")


class ClaimValidator:
    def __init__(self, facts: list[Fact], question: str, rec_prefixes: list[str],
                 rec_labels: dict[str, str] | None = None):
        self.facts = {f.id: f for f in facts}
        self.question = question
        self.prefixes = rec_prefixes
        self.labels = rec_labels or {}
        self.corpus = " ".join(f.text for f in facts) + " " + question
        self.report = ValidationReport()
        self._seen: set[str] = set()

    def _allowed_numbers(self, ids: list[str]) -> list[Number]:
        """Numbers (with units) of the cited facts only."""
        nums: list[Number] = []
        for i in ids:
            f = self.facts.get(i)
            if f:
                nums += _numbers(f.text)
        return nums

    def _render(self, text: str) -> str | None:
        """Replace option references (R1) with venue names and strip inline fact ids; None if a reference is unknown."""
        unknown = False

        def name(m: re.Match) -> str:
            nonlocal unknown
            label = self.labels.get(m.group(1))
            if label is None:
                unknown = True
                return m.group(0)
            return label

        out = FACT_REF_RE.sub("", text)
        out = REC_REF_RE.sub(name, out)
        out = re.sub(r"\s{2,}", " ", out).replace(" .", ".").replace(" ,", ",").strip()
        return None if unknown else out

    def item(self, raw: dict | None, require_prefix: str | None = None,
             must_cite: str | None = None) -> NarrativeItem | None:
        """`require_prefix`: cite this option and no other; `must_cite`: cite this option (others allowed)."""
        if not isinstance(raw, dict):
            return None
        text = str(raw.get("text") or "").strip()
        ids = [i for i in (raw.get("facts") or []) if isinstance(i, str) and i in self.facts]
        if not text:
            return None
        key = re.sub(r"[^a-z0-9]", "", text.lower())
        if key in self._seen:
            return None
        ok = True
        cite = require_prefix or must_cite
        if cite and not any(i.startswith(cite + "F") for i in ids):
            ok = False
        if require_prefix:
            other = [p for p in self.prefixes if p != require_prefix]
            if any(i.startswith(p + "F") for p in other for i in ids):
                ok = False
        nums = _numbers(text)
        if nums and not ids:
            ok = False
        if ok and nums:
            allowed = self._allowed_numbers(ids)
            ok = all(_num_ok(n, allowed) for n in nums)
        if ok and not _caps_ok(text, self.corpus):
            ok = False
        if ok and not _conditions_ok(text, self.corpus.lower()):
            ok = False
        if ok and any(re.search(p, text, re.I) for p in BANNED):
            ok = False
        rendered = self._render(text) if ok else None
        if not rendered:
            self.report.removed += 1
            return None
        self.report.kept += 1
        self._seen.add(key)
        return NarrativeItem(text=rendered, fact_ids=ids)

    def items(self, raws, limit: int) -> list[NarrativeItem]:
        out = []
        for r in (raws or [])[:limit]:
            it = self.item(r)
            if it:
                out.append(it)
        return out

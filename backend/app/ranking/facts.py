"""Deterministic fact registry, reasons and advice for ranked recommendations.

Every fact is a pre-rendered sentence built only from retrieved or derived evidence, with an id
(e.g. "R1F3") and the numbers it contains. The SLM may only cite these ids; the claim validator checks
numbers against them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from app.geo.activity_tags import CATEGORY_LABELS
from app.ranking import thresholds as th
from app.ranking.activities import ActivityProfile
from app.ranking.ranker import EvaluatedSlot, VenueEvaluation
from app.ranking.safety import UserProfile
from app.schemas.responses import Fact, Reason
from app.utils.units import compass

NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def numbers_in(text: str) -> list[float]:
    return [float(x) for x in NUM_RE.findall(text.replace(",", ""))]


def fmt_time(dt, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%a %d %b %H:%M")


def fmt_clock(dt, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).strftime("%H:%M")


@dataclass
class FactBook:
    facts: list[Fact] = field(default_factory=list)

    def add(self, prefix: str, text: str, evidence_ids: list[str]) -> str:
        fid = f"{prefix}F{sum(1 for f in self.facts if f.id.startswith(prefix + 'F')) + 1}"
        self.facts.append(Fact(id=fid, text=text, evidence_ids=evidence_ids, numbers=numbers_in(text)))
        return fid


@dataclass
class RecFacts:
    ids: dict[str, str]  # topic -> fact id
    positives: list[Reason]
    negatives: list[Reason]
    advice: list[Reason]
    watch_for: list[Reason]
    postpone_if: list[Reason]


COMPONENT_TOPIC = {
    "thermal": "heat", "precipitation": "rain", "wind": "wind", "air_quality": "air", "daylight": "daylight",
    "uv": "uv", "travel": "travel", "context": "context", "surface": "surface", "visibility": "visibility",
    "sky": "sky", "golden_hour": "sun", "venue_fit": "venue", "space": "venue",
}


def build_rec_facts(
    book: FactBook,
    prefix: str,
    v: VenueEvaluation,
    best: EvaluatedSlot,
    profile: ActivityProfile,
    user: UserProfile,
    tz: ZoneInfo,
    requested: EvaluatedSlot | None = None,
) -> RecFacts:
    venue, c = v.ev.venue, best.cond
    ids: dict[str, str] = {}
    W, A = "weather:open-meteo", "air:open-meteo"
    cat = CATEGORY_LABELS.get(venue.category, venue.category)
    ids["venue"] = book.add(prefix, f"{venue.display_label} is a mapped {cat} {venue.distance_km:.1f} km "
                            f"(straight line) from the starting point.", [venue.source_id])
    ids["slot"] = book.add(prefix, f"Best time slot: {fmt_time(best.slot.start, tz)} to {fmt_clock(best.slot.end, tz)} "
                           f"({tz.key}).", ["derived:engine"])
    t = v.ev.travel
    if t and t.duration_min is not None:
        if t.route_km is None:
            dist = ""
        else:
            dist = ", under 0.1 km" if t.route_km < 0.1 else f", {t.route_km:.1f} km"
        mins = "under 1 min" if t.duration_min < 1 else f"about {t.duration_min:.0f} min"
        ids["travel"] = book.add(prefix, f"Estimated {t.mode} time {mins}{dist} "
                                 "(OSRM free-flow estimate, no live traffic).", [f"routing:osrm:{t.mode}"])
    elif t:
        ids["travel"] = book.add(prefix, f"Route time unavailable; straight-line distance {t.straight_km:.1f} km.",
                                 ["derived:engine"])
    if c.temperature_c.value is not None:
        hi = c.heat_index_c.value
        extra = f", heat index (feels-like) up to {hi:.0f} C" if hi is not None else ""
        ids["heat"] = book.add(prefix, f"Forecast temperature up to {c.temperature_c.value:.0f} C{extra}.", [W])
    if c.precip_probability_pct.value is not None:
        mm = c.precip_mm.value
        ids["rain"] = book.add(prefix, f"Rain probability up to {c.precip_probability_pct.value:.0f}%"
                               + (f", {mm:.1f} mm expected" if mm is not None else "") + " (forecast).", [W])
    if c.prior_precip_mm.value is not None and profile.prior_rain_hours:
        ids["surface"] = book.add(prefix, f"{c.prior_precip_mm.value:.1f} mm of rain forecast in the "
                                  f"{profile.prior_rain_hours} h before the slot.", [W])
    if c.wind_kmh.value is not None:
        d = compass(c.wind_direction_deg.value)
        g = c.gust_kmh.value
        ids["wind"] = book.add(prefix, f"Wind up to {c.wind_kmh.value:.0f} km/h" + (f", gusts {g:.0f} km/h" if g is not None else "")
                               + (f" from the {d}" if d else "") + " (forecast).", [W])
    if c.us_aqi.value is not None:
        pm = c.pm2_5.value
        ids["air"] = book.add(prefix, f"Modelled US AQI up to {c.us_aqi.value:.0f}"
                              + (f", PM2.5 up to {pm:.0f} ug/m3" if pm is not None else "")
                              + " (CAMS regional model via Open-Meteo, not a local measurement).", [A])
    else:
        ids["air"] = book.add(prefix, "Air-quality data is unavailable for this slot.", [A])
    if c.uv_index.value is not None and c.daylight is not False:
        ids["uv"] = book.add(prefix, f"UV index up to {c.uv_index.value:.0f}.", [W])
    if c.visibility_m.value is not None and profile.activity.value in ("hiking", "photography", "cycling"):
        ids["visibility"] = book.add(prefix, f"Visibility at least {c.visibility_m.value / 1000:.1f} km (forecast).", [W])
    if c.cloud_cover_pct.value is not None and profile.activity.value == "photography":
        ids["sky"] = book.add(prefix, f"Average cloud cover {c.cloud_cover_pct.value:.0f}% during the slot.", [W])
    if c.sunset is not None and profile.daylight in ("required", "golden_hour", "preferred"):
        ids["sun"] = book.add(prefix, f"Sunrise {fmt_clock(c.sunrise, tz) if c.sunrise else 'n/a'}, "
                              f"sunset {fmt_clock(c.sunset, tz)} local time.", [W])
    ctx = v.ev.context
    if ctx is not None:
        bits = []
        if ctx.nearest_road_m is not None:
            bits.append(f"nearest major road ({ctx.road_class}) about {ctx.nearest_road_m:.0f} m from the venue centre")
        else:
            bits.append("no major road mapped within 1 km")
        if ctx.green_share is not None:
            bits.append(f"{ctx.green_share * 100:.0f}% mapped green cover within 500 m")
        if ctx.nearest_industrial_m is not None and ctx.nearest_industrial_m <= 2000:
            bits.append(f"industrial land use about {ctx.nearest_industrial_m:.0f} m away")
        ids["context"] = book.add(prefix, "Surroundings (from OpenStreetMap): " + "; ".join(bits) + ".", ["context:overpass"])
    if best.upwind:
        ids["upwind"] = book.add(prefix, "Wind blows from the direction of: " + "; ".join(best.upwind)
                                 + " (map-based indicator, not a pollution measurement).", ["context:overpass", W])
    if best.score:
        ids["score"] = book.add(prefix, f"Overall score {best.score.total:.0f}/100 with {best.score.confidence} "
                                f"data completeness.", ["derived:engine"])
    for i, w in enumerate(best.safety.cautions + best.safety.gaps):
        ids[f"warn{i}"] = book.add(prefix, w.message, w.evidence_ids)
    if requested is not None and requested is not best:
        status = {"excluded": "not advised", "unverified": "could not be verified",
                  "caution": "possible with cautions", "suitable": "suitable"}[requested.status]
        reason = ""
        if requested.safety.exclusions:
            reason = ": " + requested.safety.exclusions[0].message
        ids["requested"] = book.add(prefix, f"The requested time {fmt_time(requested.slot.start, tz)} is {status}{reason}",
                                    ["derived:engine"])

    positives, negatives = [], []
    if best.score:
        for comp in best.score.components:
            if comp.score is None:
                continue
            fid = ids.get(COMPONENT_TOPIC.get(comp.name, ""), "")
            reason = Reason(text=comp.explanation, fact_ids=[fid] if fid else [])
            if comp.score >= 0.8:
                positives.append(reason)
            elif comp.score <= 0.45:
                negatives.append(reason)
    if venue.suitability_note:
        negatives.append(Reason(text=venue.suitability_note, fact_ids=[ids["venue"]]))

    advice, watch, postpone = _advice(profile, best, user, ids, tz)
    return RecFacts(ids, positives, negatives, advice, watch, postpone)


def _advice(profile: ActivityProfile, best: EvaluatedSlot, user: UserProfile, ids: dict[str, str], tz: ZoneInfo):
    c = best.cond
    advice = [Reason(text=a) for a in profile.base_advice]
    watch: list[Reason] = []
    postpone: list[Reason] = [Reason(text="Postpone and get indoors if you hear thunder or see lightning.")]
    hi = c.heat_index_c.value
    if profile.strenuous or (hi is not None and hi >= th.HEAT_INDEX_CAUTION_C):
        advice.append(Reason(text="Carry enough drinking water for the whole session.", fact_ids=[ids.get("heat", "")] if ids.get("heat") else []))
    if hi is not None and hi >= th.HEAT_INDEX_EXTREME_CAUTION_C:
        advice.append(Reason(text="Wear light, breathable clothing and plan shade breaks.", fact_ids=[ids["heat"]]))
        watch.append(Reason(text="Watch for dizziness, cramps or nausea - signs of heat stress.", fact_ids=[ids["heat"]]))
    uv = c.uv_index.value
    if uv is not None and uv >= th.UV_HIGH:
        advice.append(Reason(text="Use sunscreen, a cap or hat and sunglasses.", fact_ids=[ids["uv"]] if "uv" in ids else []))
    pp = c.precip_probability_pct.value
    if pp is not None and pp >= 30:
        advice.append(Reason(text="Carry a rain jacket or umbrella.", fact_ids=[ids["rain"]]))
        watch.append(Reason(text="Check the radar or forecast again shortly before leaving.", fact_ids=[ids["rain"]]))
    if c.daylight is False or profile.daylight == "golden_hour":
        advice.append(Reason(text="Carry a torch or phone light for the walk back in low light."))
    g = c.gust_kmh.value
    if g is not None and g >= 30 and profile.activity.value in ("outdoor_event", "picnic", "photography"):
        advice.append(Reason(text="Secure light items; use weights for tents, banners or a tripod.", fact_ids=[ids["wind"]]))
    if user.respiratory:
        advice.append(Reason(text="Keep your reliever inhaler with you, as prescribed by your doctor."))
        watch.append(Reason(text="Stop and rest if you notice wheezing, chest tightness or breathlessness."))
        postpone.append(Reason(text="Postpone if the air-quality forecast worsens to US AQI above 100.", fact_ids=[ids["air"]]))
    if user.heat_sensitive:
        postpone.append(Reason(text=f"Postpone if the heat index forecast rises above {th.HEAT_INDEX_EXTREME_CAUTION_C:.0f} C.",
                               fact_ids=[ids["heat"]] if "heat" in ids else []))
    elif profile.strenuous:
        postpone.append(Reason(text=f"Postpone if the heat index forecast rises above {th.HEAT_INDEX_DANGER_C:.0f} C.",
                               fact_ids=[ids["heat"]] if "heat" in ids else []))
    if profile.prior_rain_hours:
        watch.append(Reason(text="Check that the surface is dry and not slippery before starting."))
    if profile.activity.value == "hiking":
        postpone.append(Reason(text="Turn back early if heavy rain starts - streams and rock can become dangerous quickly."))
    if best.upwind:
        watch.append(Reason(text="Wind is blowing from mapped roads or industry towards the venue; sensitive "
                             "people may prefer an alternative.", fact_ids=[ids["upwind"]]))
    return advice, watch, postpone

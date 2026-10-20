"""Deterministic, explainable component scoring.

total = 100 * (sum_i w_i * s_i / sum_{i available} w_i) * (1 - 0.5 * missing_weight_share)

Missing components are excluded from the weighted mean (never scored as favourable) and the total is
reduced by half of the missing weight share. Each component reports the evidence ids it used.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.ranking import curves
from app.ranking.activities import ActivityProfile
from app.ranking.safety import UserProfile
from app.ranking.time_slots import Slot
from app.schemas.responses import ScoreBreakdown, ScoreComponent, SlotConditions
from app.schemas.venue import Venue
from app.utils.units import compass

MISSING_PENALTY = 0.5

DIST_KM: dict[str, curves.Curve] = {
    "driving": ((0, 1.0), (3, 1.0), (8, 0.75), (15, 0.5), (30, 0.25), (50, 0.05)),
    "cycling": ((0, 1.0), (2, 1.0), (5, 0.7), (10, 0.4), (20, 0.1)),
    "walking": ((0, 1.0), (0.8, 1.0), (2, 0.7), (4, 0.35), (8, 0.05)),
}
DESTINATION_ACTIVITIES = {"golf", "hiking", "photography"}


@dataclass
class TravelEvidence:
    mode: str
    duration_min: float | None
    route_km: float | None
    straight_km: float


@dataclass
class ContextEvidence:
    nearest_road_m: float | None
    road_class: str | None
    nearest_industrial_m: float | None
    green_share: float | None
    nearest_water_m: float | None
    water_bearing_deg: float | None


def _c(name, score, ids, expl) -> tuple[str, float | None, list[str], str]:
    return name, (None if score is None else round(max(0.0, min(1.0, score)), 3)), ids, expl


def _overlap_min(a0, a1, b0, b1) -> float:
    return max(0.0, (min(a1, b1) - max(a0, b0)).total_seconds() / 60)


def component_scores(
    profile: ActivityProfile,
    slot: Slot,
    cond: SlotConditions,
    venue: Venue,
    travel: TravelEvidence | None,
    ctx: ContextEvidence | None,
    user: UserProfile,
    objective: str,
    preferences: set[str],
) -> list[tuple[str, float | None, list[str], str]]:
    W, A = "weather:open-meteo", "air:open-meteo"
    out = []
    for name in profile.weights:
        if name == "thermal":
            hi, t = cond.heat_index_c.value, cond.temperature_c.value
            shift = 3.0 if user.heat_sensitive else 0.0
            hs = curves.interp(profile.heat_curve, None if hi is None else hi + shift)
            cs = curves.interp(curves.COLD, t)
            s = None if hs is None and cs is None else min(x for x in (hs, cs) if x is not None)
            expl = f"Heat index up to {hi:.0f} C" if hi is not None else "Temperature data unavailable"
            out.append(_c(name, s, [W], expl))
        elif name == "precipitation":
            pp, mm = cond.precip_probability_pct.value, cond.precip_mm.value
            hours = max(1, int((slot.end - slot.start).total_seconds() // 3600))
            parts = [curves.interp(curves.PRECIP_PROB, pp), curves.interp(curves.PRECIP_MM, None if mm is None else mm / hours)]
            parts = [p for p in parts if p is not None]
            s = min(parts) if parts else None
            expl = (f"Rain probability up to {pp:.0f}%, {mm:.1f} mm expected" if pp is not None and mm is not None
                    else "Precipitation forecast unavailable")
            out.append(_c(name, s, [W], expl))
        elif name == "wind":
            w, g = cond.wind_kmh.value, cond.gust_kmh.value
            eff = None if w is None and g is None else max(w or 0, 0.7 * (g or 0))
            d = compass(cond.wind_direction_deg.value)
            expl = f"Wind up to {w:.0f} km/h, gusts {g:.0f} km/h" + (f" from the {d}" if d else "") if w is not None and g is not None else "Wind forecast unavailable"
            out.append(_c(name, curves.interp(profile.wind_curve, eff), [W], expl))
        elif name == "air_quality":
            aqi = cond.us_aqi.value
            curve = curves.AQI_SENSITIVE if user.air_sensitive else curves.AQI
            expl = f"Modelled US AQI up to {aqi:.0f}" if aqi is not None else "Air-quality data unavailable"
            out.append(_c(name, curves.interp(curve, aqi), [A], expl))
        elif name == "daylight":
            lit = venue.tags.get("lit") == "yes"
            if cond.daylight is None:
                out.append(_c(name, None, [W], "Daylight unknown"))
            elif cond.daylight:
                out.append(_c(name, 1.0, [W], "Entirely in daylight"))
            else:
                out.append(_c(name, 0.8 if lit else 0.35, [W],
                              "Partly after dark" + (" (venue mapped as lit)" if lit else " (venue not mapped as lit)")))
        elif name == "uv":
            uv = cond.uv_index.value
            out.append(_c(name, curves.interp(curves.UV, uv), [W],
                          f"UV index up to {uv:.0f}" if uv is not None else "UV forecast unavailable"))
        elif name == "travel":
            if travel is None:
                out.append(_c(name, None, [], "Travel information unavailable"))
            elif travel.duration_min is not None:
                curve = curves.TRAVEL_MIN_DESTINATION if profile.activity.value in DESTINATION_ACTIVITIES else curves.TRAVEL_MIN
                when = ("Under 1 min" if travel.duration_min < 1 else f"About {travel.duration_min:.0f} min")
                out.append(_c(name, curves.interp(curve, travel.duration_min), [f"routing:osrm:{travel.mode}"],
                              f"{when} by {travel.mode} (free-flow estimate)"))
            else:
                curve = DIST_KM.get(travel.mode, DIST_KM["driving"])
                if profile.activity.value in DESTINATION_ACTIVITIES:
                    curve = [(x * 2, y) for x, y in curve]
                out.append(_c(name, curves.interp(curve, travel.straight_km), ["derived:engine"],
                              f"{travel.straight_km:.1f} km straight-line (route time unavailable)"))
        elif name == "context":
            if ctx is None:
                out.append(_c(name, None, ["context:overpass"], "Surroundings data unavailable"))
            else:
                parts, bits = [], []
                if ctx.nearest_road_m is not None:
                    parts.append(curves.interp(curves.ROAD_DISTANCE_M, ctx.nearest_road_m))
                    bits.append(f"major road ~{ctx.nearest_road_m:.0f} m")
                else:
                    parts.append(1.0)
                    bits.append("no major road within 1 km")
                parts.append(curves.interp(curves.INDUSTRIAL_M, ctx.nearest_industrial_m) if ctx.nearest_industrial_m is not None else 1.0)
                if ctx.green_share is not None:
                    parts.append(curves.interp(curves.GREEN_SHARE, ctx.green_share))
                    bits.append(f"{ctx.green_share * 100:.0f}% green cover within 500 m")
                out.append(_c(name, sum(parts) / len(parts), ["context:overpass"], "; ".join(bits)))
        elif name == "surface":
            prior = cond.prior_precip_mm.value
            out.append(_c(name, curves.interp(curves.PRIOR_RAIN_MM, prior), [W],
                          f"{prior:.1f} mm rain in the {profile.prior_rain_hours or 6} h before" if prior is not None
                          else "Recent rainfall unknown"))
        elif name == "visibility":
            v = cond.visibility_m.value
            out.append(_c(name, curves.interp(curves.VISIBILITY_M, v), [W],
                          f"Visibility at least {v / 1000:.1f} km" if v is not None else "Visibility unavailable"))
        elif name == "sky":
            cc, low = cond.cloud_cover_pct.value, cond.cloud_cover_low_pct.value
            if cc is None:
                out.append(_c(name, None, [W], "Cloud forecast unavailable"))
            elif objective == "night":
                out.append(_c(name, 1 - cc / 100, [W], f"Cloud cover {cc:.0f}%"))
            else:
                parts = [curves.interp(curves.SKY_GOLDEN, cc)]
                if low is not None:
                    parts.append(curves.interp(curves.LOW_CLOUD_GOLDEN, low))
                out.append(_c(name, min(parts), [W], f"Cloud cover {cc:.0f}%" + (f" (low cloud {low:.0f}%)" if low is not None else "")))
        elif name == "golden_hour":
            sr, ss = cond.sunrise, cond.sunset
            if ss is None and sr is None:
                out.append(_c(name, None, [W], "Sunrise/sunset times unavailable"))
                continue
            sunset_ov = _overlap_min(slot.start, slot.end, ss - timedelta(minutes=60), ss + timedelta(minutes=15)) if ss else 0
            sunrise_ov = _overlap_min(slot.start, slot.end, sr - timedelta(minutes=15), sr + timedelta(minutes=60)) if sr else 0
            if objective == "sunset":
                s, expl = min(1.0, sunset_ov / 45), f"{sunset_ov:.0f} min of the sunset golden hour"
            elif objective == "sunrise":
                s, expl = min(1.0, sunrise_ov / 45), f"{sunrise_ov:.0f} min of the sunrise golden hour"
            elif objective == "night":
                dark = ss is not None and slot.start >= ss + timedelta(minutes=60)
                s, expl = (1.0, "After astronomical dusk approx.") if dark else (0.2, "Not fully dark")
            else:
                best = max(sunset_ov, sunrise_ov)
                s = 1.0 if best >= 30 else (0.6 if cond.daylight else 0.2)
                expl = f"{best:.0f} min of golden-hour light" if best else ("Daylight" if cond.daylight else "Low light")
            out.append(_c(name, s, [W], expl))
        elif name == "venue_fit":
            s = 1.0 if venue.suitability == "explicit" else 0.6
            notes = ["mapped specifically for this activity" if venue.suitability == "explicit" else "suitability inferred from map tags"]
            if ctx and "water_view" in preferences and ctx.nearest_water_m is not None and ctx.nearest_water_m <= 500:
                s += 0.15
                notes.append("near water")
            if "lit" in preferences and venue.tags.get("lit") == "yes":
                s += 0.15
                notes.append("lit")
            if ctx and preferences & {"greenery", "shade"} and (ctx.green_share or 0) >= 0.3:
                s += 0.1
                notes.append("green surroundings")
            if profile.activity.value == "photography" and ctx and ctx.nearest_water_m is not None and ctx.nearest_water_m <= 2000 and ctx.water_bearing_deg is not None:
                b = ctx.water_bearing_deg
                if (objective == "sunset" and 225 <= b <= 315) or (objective == "sunrise" and 45 <= b <= 135):
                    s += 0.2
                    notes.append(f"water lies to the {'west' if objective == 'sunset' else 'east'} (towards the sun)")
            out.append(_c(name, s, [venue.source_id], "Venue " + ", ".join(notes)))
        elif name == "space":
            area = venue.area_m2
            out.append(_c(name, curves.interp(curves.AREA_M2_EVENT, area), [venue.source_id],
                          f"Mapped footprint ~{area:,.0f} m2 (bounding box)" if area else "Venue size not mapped"))
    return out


def adjusted_weights(profile: ActivityProfile, user: UserProfile) -> dict[str, float]:
    w = dict(profile.weights)
    if user.air_sensitive and "air_quality" in w:
        w["air_quality"] *= 1.6
    if user.heat_sensitive and "thermal" in w:
        w["thermal"] *= 1.3
    if "limited_mobility" in user.sensitivities and "travel" in w:
        w["travel"] *= 1.3
    return w


def combine(components: list[tuple[str, float | None, list[str], str]], weights: dict[str, float], margin: float) -> ScoreBreakdown:
    total_w = sum(weights[n] for n, *_ in components) or 1.0
    avail_w = sum(weights[n] for n, s, *_ in components if s is not None)
    missing_share = 1 - avail_w / total_w
    factor = 1 - MISSING_PENALTY * missing_share
    comps: list[ScoreComponent] = []
    total = 0.0
    for name, s, ids, expl in components:
        w = weights[name]
        contrib = 0.0 if s is None or avail_w == 0 else 100 * w * s / avail_w * factor
        total += contrib
        comps.append(ScoreComponent(name=name, score=s, weight=round(w / total_w, 3), contribution=round(contrib, 1),
                                    evidence_ids=ids, explanation=expl))
    completeness = round(1 - missing_share, 3)
    confidence = "high" if completeness >= 0.9 else ("medium" if completeness >= 0.7 else "low")
    return ScoreBreakdown(total=round(min(100.0, total), 1), completeness=completeness, confidence=confidence,
                          safety_margin=margin, components=comps)

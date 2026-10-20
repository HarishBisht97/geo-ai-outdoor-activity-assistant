"""Safety filtering - applied BEFORE ranking. A high score never overrides an exclusion.

Outputs three distinct kinds of finding:
- `avoid`    : hard exclusion (the slot cannot be recommended)
- `caution`  : allowed, but the user must be told
- `data_gap` : evidence needed to judge safety is missing (slot becomes "unverified" if critical)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from app.ranking import thresholds as th
from app.ranking.activities import ActivityProfile
from app.ranking.conditions import SeriesIndex, slot_hours
from app.ranking.time_slots import Slot
from app.schemas.common import WarningItem
from app.schemas.responses import SlotConditions, SlotStatus
from app.schemas.venue import Venue
from app.utils.units import THUNDER_CODES


@dataclass
class UserProfile:
    sensitivities: set[str] = field(default_factory=set)
    children: bool = False
    elderly: bool = False

    @property
    def respiratory(self) -> bool:
        return "respiratory" in self.sensitivities

    @property
    def heat_sensitive(self) -> bool:
        return "heat_sensitive" in self.sensitivities or self.children or self.elderly

    @property
    def air_sensitive(self) -> bool:
        return self.respiratory or self.children or self.elderly

    def labels(self) -> list[str]:
        out = sorted(self.sensitivities)
        if self.children:
            out.append("children")
        if self.elderly:
            out.append("elderly")
        return out


@dataclass
class SafetyResult:
    exclusions: list[WarningItem] = field(default_factory=list)
    cautions: list[WarningItem] = field(default_factory=list)
    gaps: list[WarningItem] = field(default_factory=list)
    critical_gap: bool = False
    margin: float = 1.0

    @property
    def status(self) -> SlotStatus:
        if self.exclusions:
            return "excluded"
        if self.critical_gap:
            return "unverified"
        if self.cautions:
            return "caution"
        return "suitable"


def _w(kind: str, code: str, msg: str, *ids: str) -> WarningItem:
    return WarningItem(type=kind, code=code, message=msg, evidence_ids=[i for i in ids if i])  # type: ignore[arg-type]


def evaluate(
    profile: ActivityProfile,
    slot: Slot,
    cond: SlotConditions,
    weather: SeriesIndex,
    venue: Venue,
    user: UserProfile,
    objective: str = "general",
    upwind: list[str] | None = None,
) -> SafetyResult:
    r = SafetyResult()
    margins: list[float] = []
    strenuous = profile.strenuous

    # --- Weather availability is critical for every activity ---------------------------------
    if cond.temperature_c.value is None and cond.precip_probability_pct.value is None:
        r.gaps.append(_w("data_gap", "weather_missing", "No weather forecast is available for this slot.",
                         "weather:open-meteo"))
        r.critical_gap = True

    # --- Thunderstorms ------------------------------------------------------------------------
    buf = profile.thunder_buffer_h
    codes = weather.values("weather_code", slot.start - timedelta(hours=buf), slot_hours(slot) + 2 * buf)
    if any(c is not None and int(c) in THUNDER_CODES for c in codes):
        extra = f" within {buf} h of" if buf else " during"
        r.exclusions.append(_w("avoid", "thunderstorm", f"Thunderstorm forecast{extra} this slot - lightning risk.",
                               "weather:open-meteo"))

    # --- Heat ---------------------------------------------------------------------------------
    hi = cond.heat_index_c.value
    if hi is not None:
        danger = th.HEAT_INDEX_DANGER_C if strenuous else th.HEAT_INDEX_EXTREME_DANGER_C
        caution_at = th.HEAT_INDEX_EXTREME_CAUTION_C
        if user.heat_sensitive:
            danger = th.HEAT_INDEX_EXTREME_CAUTION_C if strenuous else th.HEAT_INDEX_DANGER_C - 2
            caution_at = th.HEAT_INDEX_CAUTION_C
        if hi >= danger:
            who = " for heat-sensitive people (children, older adults or as stated)" if user.heat_sensitive else ""
            r.exclusions.append(_w("avoid", "heat", f"Heat index {hi:.0f} C reaches the exclusion limit of "
                                   f"{danger:.0f} C{who}.", "weather:open-meteo"))
        elif hi >= caution_at:
            r.cautions.append(_w("caution", "heat", f"Heat index {hi:.0f} C is in the NWS caution range; "
                                 "take shade and water breaks.", "weather:open-meteo"))
        margins.append(max(0.0, min(1.0, (danger - hi) / 14)))
    t = cond.temperature_c.value
    if t is not None and t <= th.COLD_CAUTION_C:
        r.cautions.append(_w("caution", "cold", f"Temperature down to {t:.0f} C; dress in layers.",
                             "weather:open-meteo"))

    # --- Wind -------------------------------------------------------------------------------
    gust = cond.gust_kmh.value
    if gust is not None:
        limit = min(profile.gust_max_kmh, th.GUST_DANGER_KMH)
        if gust >= limit:
            r.exclusions.append(_w("avoid", "wind", f"Wind gusts up to {gust:.0f} km/h exceed the {limit:.0f} km/h "
                                   f"limit for {profile.label.lower()}.", "weather:open-meteo"))
        elif gust >= 0.75 * limit:
            r.cautions.append(_w("caution", "wind", f"Gusty: up to {gust:.0f} km/h.", "weather:open-meteo"))
        margins.append(max(0.0, min(1.0, (limit - gust) / limit)))

    # --- Rain -------------------------------------------------------------------------------
    mm, n = cond.precip_mm.value, slot_hours(slot)
    if mm is not None and profile.heavy_rain_excludes and mm / n >= th.HEAVY_RAIN_MM_PER_H:
        r.exclusions.append(_w("avoid", "heavy_rain", f"Heavy rain forecast ({mm:.1f} mm over the slot).",
                               "weather:open-meteo"))
    pp = cond.precip_probability_pct.value
    if pp is not None:
        if pp >= th.RAIN_LIKELY_PCT:
            r.cautions.append(_w("caution", "rain_likely", f"Rain is likely (up to {pp:.0f}% probability).",
                                 "weather:open-meteo"))
        margins.append(max(0.0, (100 - pp) / 100))
    if profile.activity.value == "hiking" and venue.category in ("waterfall", "peak", "fort") and mm and mm >= 2:
        r.exclusions.append(_w("avoid", "trail_rain", f"Rain ({mm:.1f} mm) at a {venue.category}: slippery rock "
                               "and flash-flow risk.", "weather:open-meteo"))
    prior = cond.prior_precip_mm.value
    if profile.prior_rain_hours and prior is not None and prior >= 3:
        r.cautions.append(_w("caution", "wet_surface", f"{prior:.1f} mm of rain is forecast in the hours before; "
                             "the playing surface may be wet.", "weather:open-meteo"))

    # --- Air quality ------------------------------------------------------------------------
    aqi = cond.us_aqi.value
    if aqi is None:
        if user.air_sensitive:
            r.gaps.append(_w("data_gap", "air_missing", "Air-quality data is unavailable for this slot, so it "
                             "cannot be confirmed as suitable for the stated sensitivity.", "air:open-meteo"))
            r.critical_gap = True
        else:
            r.gaps.append(_w("data_gap", "air_missing", "Air-quality data is unavailable for this slot.",
                             "air:open-meteo"))
    else:
        if aqi >= th.AQI_VERY_UNHEALTHY:
            r.exclusions.append(_w("avoid", "aqi", f"Modelled US AQI {aqi:.0f} is 'Very Unhealthy' or worse.",
                                   "air:open-meteo"))
        elif aqi >= th.AQI_UNHEALTHY and user.air_sensitive:
            r.exclusions.append(_w("avoid", "aqi_sensitive", f"Modelled US AQI {aqi:.0f} is 'Unhealthy' - not "
                                   "advised for the stated sensitivity.", "air:open-meteo"))
        elif aqi >= th.AQI_UNHEALTHY:
            effort = "keep the effort light and take breaks" if strenuous else "limit prolonged time outdoors"
            r.cautions.append(_w("caution", "aqi", f"Modelled US AQI {aqi:.0f} is 'Unhealthy' for everyone: "
                                 f"{effort}.", "air:open-meteo"))
        elif aqi >= th.AQI_USG and user.air_sensitive and strenuous:
            r.exclusions.append(_w("avoid", "aqi_sensitive", f"Modelled US AQI {aqi:.0f} is 'Unhealthy for "
                                   "Sensitive Groups' - not advised for the stated sensitivity.", "air:open-meteo"))
        elif aqi >= th.AQI_USG:
            r.cautions.append(_w("caution", "aqi", f"Modelled US AQI {aqi:.0f}: unhealthy for sensitive groups.",
                                 "air:open-meteo"))
        elif aqi >= th.AQI_MODERATE and user.air_sensitive:
            r.cautions.append(_w("caution", "aqi_sensitive", f"Modelled US AQI {aqi:.0f} is 'Moderate'; people "
                                 "with respiratory sensitivity may notice symptoms.", "air:open-meteo"))
        limit = th.AQI_USG if user.air_sensitive else th.AQI_VERY_UNHEALTHY
        margins.append(max(0.0, min(1.0, (limit - aqi) / limit)))
        if user.respiratory:
            r.cautions.append(_w("caution", "aqi_uncertainty", "Air quality is a regional model estimate and "
                                 "local levels (e.g. near traffic) can be higher.", "air:open-meteo"))

    # --- Daylight ---------------------------------------------------------------------------
    lit = venue.tags.get("lit") == "yes"
    if profile.daylight == "required":
        if cond.daylight is None:
            r.gaps.append(_w("data_gap", "daylight_unknown", "Daylight could not be determined for this slot.",
                             "weather:open-meteo"))
            r.critical_gap = True
        elif not cond.daylight:
            r.exclusions.append(_w("avoid", "darkness", "Part of this slot is after dark; this activity needs "
                                   "daylight.", "weather:open-meteo"))
    elif profile.daylight == "preferred" and cond.daylight is False and not lit:
        r.cautions.append(_w("caution", "darkness", "Part of this slot is after dark and the venue is not mapped "
                             "as lit.", "weather:open-meteo"))
    if (profile.end_before_sunset_min and cond.sunset is not None
            and slot.end > cond.sunset - timedelta(minutes=profile.end_before_sunset_min)):
        r.exclusions.append(_w("avoid", "late_finish", f"A {profile.duration_min // 60} h hike starting at this "
                                   f"time would finish less than {profile.end_before_sunset_min} minutes before sunset.",
                                   "weather:open-meteo"))

    vis = cond.visibility_m.value
    if vis is not None and profile.activity.value in ("cycling", "hiking"):
        if vis < th.VERY_LOW_VISIBILITY_M:
            r.exclusions.append(_w("avoid", "visibility", f"Visibility down to {vis:.0f} m.", "weather:open-meteo"))
        elif vis < th.LOW_VISIBILITY_M:
            r.cautions.append(_w("caution", "visibility", f"Low visibility (down to {vis:.0f} m).",
                                 "weather:open-meteo"))

    uv = cond.uv_index.value
    if uv is not None and uv >= th.UV_VERY_HIGH:
        r.cautions.append(_w("caution", "uv", f"UV index up to {uv:.0f} (very high): use sun protection.",
                             "weather:open-meteo"))

    if upwind and user.air_sensitive:
        r.cautions.append(_w("caution", "upwind_source", "Mapped source(s) upwind of the venue: " + "; ".join(upwind)
                             + ". This is a map-based indicator, not a measurement.", "context:overpass"))

    if "limited_mobility" in user.sensitivities and profile.activity.value == "hiking":
        r.cautions.append(_w("caution", "mobility", "Trail difficulty and surface are not reliably mapped; check "
                             "accessibility before going.", venue.source_id))

    r.margin = round(min(margins), 3) if margins else 0.0
    return r

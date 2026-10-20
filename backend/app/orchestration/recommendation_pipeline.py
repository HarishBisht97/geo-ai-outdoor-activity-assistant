"""End-to-end recommendation pipeline.

question -> intent (SLM, rules fallback) -> validation/clarification -> geocode -> candidates + origin forecast
-> time window -> parallel evidence (weather, air, context, routing, elevation) -> place x time evaluation
-> safety -> scoring -> ranking -> facts -> (stream ranking) -> SLM explanation -> claim validation -> response.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app import API_VERSION, ENGINE_VERSION, RULES_VERSION
from app.core.config import Settings
from app.core.logging import log_event
from app.geo.activity_tags import CATEGORY_LABELS
from app.geo.candidates import to_venue
from app.geo.projection import haversine_km
from app.geo.spatial_context import ContextAnalyzer
from app.orchestration import intent_resolution as ir
from app.ranking.activities import get_profile, photography_objective, profile_key
from app.ranking.conditions import SeriesIndex, hourly_points
from app.ranking.facts import FactBook, build_rec_facts, fmt_clock, fmt_time, numbers_in
from app.ranking.ranker import (
    VenueEvaluation,
    VenueEvidence,
    alternative_slots,
    evaluate_venue,
    rank,
    summarize_exclusions,
)
from app.ranking.safety import UserProfile
from app.ranking.scoring import ContextEvidence, TravelEvidence
from app.ranking.time_slots import generate_slots
from app.schemas.common import Coordinates, EvidenceValue, Provenance, WarningItem
from app.schemas.intent import Activity
from app.schemas.requests import RecommendRequest
from app.schemas.responses import (
    AlternativeSlot,
    CandidateSummary,
    Clarification,
    ContextIndicators,
    Fact,
    HourlySeries,
    ModelInfo,
    Narrative,
    ProviderStatus,
    Recommendation,
    RecommendResponse,
    ResolvedIntent,
    ResolvedPlace,
    ResolvedWindow,
    SlotResult,
    SunTimes,
    Timeline,
    TimelineCell,
    TimelineRow,
    TravelInfo,
)
from app.schemas.venue import Venue
from app.services import geocoding
from app.services.base import ServiceDeps, keep_running, make_provenance
from app.services.open_meteo import coord_key, fetch_air_quality, fetch_elevations, fetch_forecasts
from app.services.osm_context import fetch_context
from app.services.osm_places import find_candidates, pin_requested, requested_venue
from app.services.routing import route_table
from app.slm import intent_parser
from app.slm.evidence_packet import build_packet
from app.slm.response_generator import explain
from app.slm.runtime import TextGenerator
from app.slm.templates import RecSummary, template_narrative
from app.utils.time_resolver import TimeResolutionError, resolve_window

logger = logging.getLogger(__name__)

Emit = Callable[[str, dict[str, Any]], Awaitable[None]] | None

DISCLAIMER = (
    "Recommendations are generated from public forecasts, modelled air quality and OpenStreetMap data, which can be "
    "wrong or incomplete. They are not medical advice. Check conditions on site and follow local rules."
)
ATTRIBUTION = [
    "Map data (c) OpenStreetMap contributors, ODbL 1.0 - https://www.openstreetmap.org/copyright",
    "Weather and air-quality data by Open-Meteo.com (CC BY 4.0); air quality from Copernicus CAMS",
    "Routing by OSRM (project-osrm.org, routing.openstreetmap.de) on OpenStreetMap data",
    "Geocoding by Nominatim (OpenStreetMap)",
]
PURPOSE = {
    "geocode": "Place-name lookup",
    "places": "Candidate venues",
    "context": "Surrounding roads, industry, water and green cover",
    "weather": "Hourly weather forecast, sunrise and sunset",
    "air": "Modelled air quality",
    "routing": "Travel time and distance",
    "elevation": "Venue elevation",
    "derived": "Calculations by this engine",
}
EVIDENCE_TIMEOUT_S = 40
RESPONSE_MARGIN_S = 4


class Pipeline:
    def __init__(self, settings: Settings, deps: ServiceDeps, slm: TextGenerator, data_mode: str = "live",
                 clock: Callable[[], datetime] | None = None):
        self.s = settings
        self.deps = deps
        self.slm = slm
        self.data_mode = data_mode
        self.clock = clock or (lambda: datetime.now(ZoneInfo("UTC")))

    # ------------------------------------------------------------------ helpers
    def _model_info(self) -> ModelInfo:
        info = self.slm.info()
        return ModelInfo(
            base_model=self.s.model_base_id, base_revision=self.s.model_base_revision,
            runtime_repo=self.s.model_repo or None, quantization=self.s.model_quant,
            parameters=2_031_739_904, loaded=bool(info.get("loaded")),
        )

    def _base(self, request_id: str, now: datetime, status: str, message: str, **kw) -> RecommendResponse:
        sources: dict[str, Provenance] = kw.pop("sources", {}) or {}
        derived = make_provenance("derived:engine", "GeoAI engine", url=None, kind="derived", license=None,
                                  attribution=None, limitations=["Heat index (NWS formula), scores, windows and "
                                                                 "geometric indicators computed by this service."])
        if sources:
            sources.setdefault("derived:engine", derived)
        return RecommendResponse(
            request_id=request_id, api_version=API_VERSION, engine_version=ENGINE_VERSION, rules_version=RULES_VERSION,
            model=self._model_info(), status=status, message=message, generated_at=self.clock(), reference_time=now,
            data_mode=self.data_mode, disclaimer=DISCLAIMER, attribution=ATTRIBUTION,
            sources=list(sources.values()),
            data_quality=[ProviderStatus(provider=p.provider, purpose=PURPOSE.get(p.id.split(":")[0], p.id),
                                         status=p.status, message=p.error) for p in sources.values()
                          if p.id != "derived:engine"],
            **kw,
        )

    # ------------------------------------------------------------------ main
    async def run(self, req: RecommendRequest, request_id: str, emit: Emit = None) -> RecommendResponse:
        s = self.s
        now = self.clock()
        t0 = time.monotonic()
        timings: dict[str, int] = {}
        sources: dict[str, Provenance] = {}
        warnings: list[WarningItem] = []

        async def stage(name: str, detail: str | None = None):
            if emit:
                await emit("stage", {"stage": name, "detail": detail})

        def mark(name: str, since: float):
            timings[name] = int((time.monotonic() - since) * 1000)

        # 1. Intent ------------------------------------------------------------------------
        await stage("understanding", "Reading your question")
        t = time.monotonic()
        result = await intent_parser.extract(self.slm, req.question, s)
        mark("intent", t)
        intent = ir.apply_overrides(result.intent, req)
        if result.parser == "rules_fallback":
            note = result.notes[0] if result.notes else ""
            why = ("did not respond in time" if "Timeout" in note else
                   "returned output that failed validation" if note == "slm_invalid_output" else
                   "is busy" if "Overloaded" in note else "is not available")
            warnings.append(WarningItem(type="data_gap", code="slm_fallback",
                                        message=f"The language model {why}, so the question was interpreted with "
                                                "keyword rules."))

        def clarify(c: Clarification, message: str) -> RecommendResponse:
            timings["total"] = int((time.monotonic() - t0) * 1000)
            return self._base(request_id, now, "needs_clarification", message, extracted=intent, clarification=c,
                              warnings=warnings, sources=sources, timings_ms=timings)

        if intent.activity is None:
            return clarify(ir.missing_activity(intent), "Which activity should I plan for?")
        if intent.activity == "unsupported":
            return clarify(ir.unsupported_activity(intent), "That activity is not supported yet.")
        activity: Activity = intent.activity  # type: ignore[assignment]
        commute = ir.is_commute(intent)
        has_origin = req.preferences.origin is not None
        need_location = not has_origin and not intent.location_text
        need_destination = commute and not intent.destination_text
        if need_location or need_destination:
            return clarify(ir.missing_location(intent, need_location, commute, need_destination),
                           "I need a starting location to search nearby." if need_location else
                           "Where are you commuting to?")

        profile = get_profile(activity, intent.activity_detail)
        pkey = profile_key(activity, intent.activity_detail)
        assumptions: list[str] = []

        # 2. Geocode -------------------------------------------------------------------------
        await stage("locating", "Finding the starting point")
        t = time.monotonic()
        origin_raw: dict | None = None
        if has_origin:
            o = req.preferences.origin
            origin = ResolvedPlace(lat=o.lat, lon=o.lon, label=o.label or f"{o.lat:.4f}, {o.lon:.4f}",
                                   source="user_coordinates")
        else:
            g = await geocoding.geocode(self.deps, intent.location_text or "")
            sources[g.provenance.id] = g.provenance
            if not g.ok:
                timings["total"] = int((time.monotonic() - t0) * 1000)
                return self._base(request_id, now, "insufficient_data",
                                  "The place-name service is unavailable right now, so the starting point could not be "
                                  "found. Please retry or share your location.", extracted=intent, warnings=warnings,
                                  sources=sources, timings_ms=timings)
            decision = geocoding.decide(g.data or [])
            if decision.reason == "not_found":
                return clarify(ir.location_not_found("location", intent.location_text or "", intent),
                               f"I couldn't find '{intent.location_text}'.")
            if decision.reason == "ambiguous":
                return clarify(ir.location_options("location", intent.location_text or "", decision.options, intent),
                               f"'{intent.location_text}' is ambiguous.")
            c = decision.chosen
            assert c is not None
            origin = ResolvedPlace(lat=c.lat, lon=c.lon, label=c.label, display_name=c.display_name, source="nominatim",
                                   source_id=g.provenance.id)
            origin_raw = c.raw
            if decision.reason == "urban_preferred":
                others = "; ".join(o.label for o in decision.options[:2])
                assumptions.append(f"'{intent.location_text}' also matches smaller places ({others}); assumed "
                                   f"{c.label}. Name the city to choose another.")
        destination: ResolvedPlace | None = None
        dest_result = None
        if commute:
            gd = await geocoding.geocode(self.deps, intent.destination_text or "")
            sources["geocode:nominatim"] = gd.provenance
            dd = geocoding.decide(gd.data or []) if gd.ok else None
            if dd is None or dd.reason == "not_found":
                return clarify(ir.location_not_found("destination", intent.destination_text or "", intent),
                               f"I couldn't find '{intent.destination_text}'.")
            if dd.reason == "ambiguous":
                return clarify(ir.location_options("destination", intent.destination_text or "", dd.options, intent),
                               f"'{intent.destination_text}' is ambiguous.")
            dest_result = dd.chosen
            destination = ResolvedPlace(lat=dest_result.lat, lon=dest_result.lon, label=dest_result.label,
                                        display_name=dest_result.display_name, source="nominatim",
                                        source_id=gd.provenance.id)
        mark("geocode", t)

        # 3. Radius / mode / duration -------------------------------------------------------
        limit = min(profile.max_radius_km, s.max_radius_km)
        radius = intent.radius_km or profile.default_radius_km
        if intent.radius_km and intent.radius_km > limit:
            assumptions.append(f"Requested radius of {intent.radius_km:g} km exceeds the {limit:g} km limit for "
                               f"{profile.label.lower()}; searched within {limit:g} km.")
        radius = min(radius, limit)
        if not intent.radius_km:
            assumptions.append(f"No distance given: searched within {radius:g} km.")
        mode = intent.travel_mode or profile.default_travel_mode
        if commute:
            mode = "cycling"
        if not intent.travel_mode and not commute:
            assumptions.append(f"Travel times are estimated for {mode}.")
        duration = intent.duration_minutes or profile.duration_min
        user = UserProfile(set(intent.sensitivities), children=intent.group.children or
                           "children" in (intent.activity_detail or ""), elderly=intent.group.elderly)

        # 4. Candidates + origin forecast (parallel) ---------------------------------------
        await stage("finding_places", f"Searching OpenStreetMap within {radius:g} km")
        t = time.monotonic()
        origin_c = Coordinates(lat=origin.lat, lon=origin.lon)
        requested_id: str | None = None
        if commute and destination and dest_result:
            places_task = asyncio.sleep(0, result=([], 1, [sources["geocode:nominatim"]]))
        else:
            places_task = find_candidates(self.deps, pkey, origin_c, radius)
        (places, n_unique, places_provs), origin_wx = await asyncio.gather(
            places_task, fetch_forecasts(self.deps, [(origin.lat, origin.lon)]))
        mark("places", t)
        places_prov = places_provs[0]
        if not commute:
            for p in places_provs:
                sources[p.id] = p
            if places_prov.id == "places:nominatim" and places_prov.status != "failed":
                warnings.append(WarningItem(
                    type="data_gap", code="places_fallback",
                    message="The Overpass venue search did not respond in time, so places were found with a "
                            "narrower Nominatim search; some smaller venues may be missing.",
                    evidence_ids=["places:nominatim"]))
        sources[origin_wx.provenance.id] = origin_wx.provenance

        if commute and destination and dest_result:
            dkm = haversine_km(origin.lat, origin.lon, destination.lat, destination.lon)
            venues = [Venue(
                id=f"nominatim:{dest_result.osm_type or 'place'}:{dest_result.osm_id or 0}", name=destination.label,
                display_label=f"Commute to {destination.label}", coords=Coordinates(lat=destination.lat, lon=destination.lon),
                osm_type=dest_result.osm_type if dest_result.osm_type in ("node", "way", "relation") else "node",
                osm_id=dest_result.osm_id or 0,
                osm_url=f"https://www.openstreetmap.org/{dest_result.osm_type}/{dest_result.osm_id}",
                category="commute_destination", suitability="explicit", distance_km=round(dkm, 2),
                source_id="geocode:nominatim")]
        else:
            target = requested_venue(origin_raw, pkey, origin_c)
            if target is not None:
                places = pin_requested(places, target, s.max_candidates)
                n_unique = max(n_unique, len(places))
                assumptions.append(f"{target.name or origin.label} is itself a mapped {CATEGORY_LABELS.get(target.selector.category, 'venue')}, "
                                   "so it is evaluated directly; other places nearby are shown as alternatives.")
                requested_id = target.uid
            venues = [to_venue(p, "geocode:nominatim" if target is not None and p is target else places_prov.id)
                      for p in places]

        # 5. Time window --------------------------------------------------------------------
        o_series = (origin_wx.data or {}).get(coord_key(origin.lat, origin.lon)) if origin_wx.data else None
        if o_series is None:
            timings["total"] = int((time.monotonic() - t0) * 1000)
            return self._base(
                request_id, now, "insufficient_data",
                "The weather forecast service is unavailable, so no place or time can be judged safe or suitable. "
                "Please try again shortly.",
                interpretation=None, extracted=intent, warnings=warnings + [WarningItem(
                    type="data_gap", code="weather_missing", message="Weather forecast unavailable.",
                    evidence_ids=["weather:open-meteo"])],
                candidates_considered=[_candidate(v, "unverified", None, ["Weather forecast unavailable"]) for v in venues],
                sources=sources, timings_ms=timings)
        tz_name = o_series.timezone
        tz = ZoneInfo(tz_name)
        sun_lookup = {d: (sr, ss) for d, sr, ss in o_series.sun}
        coverage_end = o_series.coverage_end("temperature_2m")
        try:
            resolved = resolve_window(intent.time, now_utc=now, tz_name=tz_name, duration_min=duration,
                                      max_days=s.max_window_days, sun=sun_lookup, forecast_end_utc=coverage_end)
        except TimeResolutionError as exc:
            timings["total"] = int((time.monotonic() - t0) * 1000)
            if exc.code == "beyond_horizon":
                return self._base(request_id, now, "insufficient_data", exc.message, extracted=intent,
                                  warnings=warnings, sources=sources, timings_ms=timings)
            return clarify(ir.time_clarification(intent, exc.message), exc.message)
        if req.preferences.time_window:
            tw = req.preferences.time_window
            s0, e0 = max(tw.start, resolved.start), min(tw.end, resolved.end)
            if e0 > s0:
                resolved.windows = [(s0, e0)]
        assumptions += resolved.assumptions

        interpretation = ResolvedIntent(
            activity=activity, activity_detail=intent.activity_detail, origin=origin, destination=destination,
            requested_venue_id=requested_id, radius_km=radius, window=ResolvedWindow(start=resolved.start, end=resolved.end, timezone=tz_name),
            duration_minutes=duration, travel_mode=mode, sensitivities=intent.sensitivities, group=intent.group,
            preferences=intent.preferences, parser=result.parser, assumptions=assumptions,
        )

        if not venues:
            timings["total"] = int((time.monotonic() - t0) * 1000)
            if places_prov.status == "failed":
                return self._base(request_id, now, "insufficient_data",
                                  "The OpenStreetMap venue search is unavailable right now, so no places could be found. "
                                  "Please try again shortly.", interpretation=interpretation, extracted=intent,
                                  warnings=warnings, sources=sources, timings_ms=timings)
            return self._base(request_id, now, "no_suitable_option",
                              f"No mapped places suitable for {profile.label.lower()} were found within {radius:g} km of "
                              f"{origin.label}. Try a larger radius or a different starting point.",
                              interpretation=interpretation, extracted=intent, warnings=warnings, sources=sources,
                              timings_ms=timings)

        # 6. Evidence (parallel) ------------------------------------------------------------
        await stage("fetching_conditions", f"Fetching forecasts and context for {len(venues)} places")
        t = time.monotonic()
        coords = [(v.coords.lat, v.coords.lon) for v in venues]
        want_elev = activity in (Activity.hiking, Activity.photography) and pkey != "nature_walk"

        async def guarded(coro, label):
            try:
                return await asyncio.wait_for(coro, EVIDENCE_TIMEOUT_S)
            except TimeoutError:
                log_event(logger, "evidence_timeout", logging.WARNING, source=label)
                return None

        ctx_task = asyncio.create_task(fetch_context(self.deps, coords))
        wx, aq, routes, elev = await asyncio.gather(
            guarded(fetch_forecasts(self.deps, coords), "weather"),
            guarded(fetch_air_quality(self.deps, coords), "air"),
            guarded(route_table(self.deps, (origin.lat, origin.lon), coords, mode), "routing"),
            guarded(fetch_elevations(self.deps, coords), "elevation") if want_elev else asyncio.sleep(0, result=None),
        )
        # Context is optional: past the soft wait it is skipped for this request and left running so the
        # result is cached for the next one.
        await asyncio.wait({ctx_task}, timeout=max(0.0, s.context_soft_wait_s - (time.monotonic() - t)))
        if ctx_task.done():
            ctx = ctx_task.result()
        else:
            ctx = None
            keep_running(ctx_task)
            log_event(logger, "context_deferred", logging.INFO)
        mark("evidence", t)

        def record(fetched, pid, provider, purpose_kind="observed"):
            if fetched is None:
                sources[pid] = make_provenance(pid, provider, url=None, kind=purpose_kind, license=None,
                                               attribution=None, status="failed", error="timed out")
                return None
            prov = fetched.provenance if hasattr(fetched, "provenance") else fetched[1]
            sources[prov.id] = prov
            return fetched

        wx = record(wx, "weather:open-meteo", "Open-Meteo Forecast API", "forecast")
        aq = record(aq, "air:open-meteo", "Open-Meteo Air Quality API (CAMS)", "modeled")
        routes = record(routes, f"routing:osrm:{mode}", "OSRM", "derived")
        if want_elev:
            elev = record(elev, "elevation:open-meteo", "Open-Meteo Elevation API")
        ctx_features = None
        if ctx is None:
            sources["context:overpass"] = make_provenance(
                "context:overpass", "OpenStreetMap via Overpass API", url=None, kind="observed", license="ODbL 1.0",
                attribution=None, status="skipped",
                error=f"No response within {s.context_soft_wait_s:g} s; skipped for this request.")
        else:
            ctx_features, ctx_prov = ctx
            sources[ctx_prov.id] = ctx_prov
        if aq is None or not aq.ok:
            warnings.append(WarningItem(type="data_gap", code="air_missing",
                                        message="Air-quality data could not be retrieved; air quality is treated as "
                                                "unknown, not as good.", evidence_ids=["air:open-meteo"]))
        if routes is None or not routes.ok:
            warnings.append(WarningItem(type="data_gap", code="routing_missing",
                                        message="Travel times could not be retrieved; straight-line distances are shown "
                                                "instead.", evidence_ids=[f"routing:osrm:{mode}"]))
        if ctx_features is None:
            warnings.append(WarningItem(type="data_gap", code="context_missing",
                                        message="Surrounding-feature data (roads, industry, green cover) is unavailable.",
                                        evidence_ids=["context:overpass"]))

        analyzer = ContextAnalyzer(ctx_features, origin.lat, origin.lon) if ctx_features is not None else None
        wx_map = wx.data if wx and wx.data else {}
        aq_map = aq.data if aq and aq.data else {}
        evidences: list[VenueEvidence] = []
        for i, v in enumerate(venues):
            if elev and elev.data and i < len(elev.data):
                v.elevation_m = elev.data[i]
            w_series = wx_map.get(coord_key(v.coords.lat, v.coords.lon))
            a_series = aq_map.get(coord_key(v.coords.lat, v.coords.lon, 0.1))
            sun = {d: (sr, ss) for d, sr, ss in w_series.sun} if w_series else sun_lookup
            travel = TravelEvidence(mode=mode, duration_min=None, route_km=None, straight_km=v.distance_km)
            if routes and routes.data and i < len(routes.data):
                leg = routes.data[i]
                if leg.duration_s is not None:
                    travel.duration_min = round(leg.duration_s / 60, 1)
                if leg.distance_m is not None:
                    travel.route_km = round(leg.distance_m / 1000, 2)
            ctx_ev, srcs = None, []
            if analyzer:
                vc = analyzer.analyze(v.coords.lat, v.coords.lon)
                ctx_ev = ContextEvidence(vc.nearest_major_road_m, vc.nearest_major_road_class, vc.nearest_industrial_m,
                                         vc.green_share_500m, vc.nearest_water_m, vc.water_bearing_deg)
                srcs = vc.sources
            evidences.append(VenueEvidence(v, SeriesIndex(w_series), SeriesIndex(a_series), sun, travel, ctx_ev, srcs))

        # 7. Slots, evaluation, ranking ------------------------------------------------------
        await stage("ranking", "Comparing places and times")
        t = time.monotonic()
        slots = generate_slots(resolved.windows, duration, coverage_end)
        if not slots:
            timings["total"] = int((time.monotonic() - t0) * 1000)
            return self._base(request_id, now, "insufficient_data",
                              "No complete time slot fits inside the requested window and the available forecast.",
                              interpretation=interpretation, extracted=intent, warnings=warnings, sources=sources,
                              timings_ms=timings)
        objective = photography_objective(intent.activity_detail, intent.time.part_of_day) if activity == Activity.photography else "general"
        prefs = set(intent.preferences)
        evaluations = [evaluate_venue(e, slots, profile, user, objective, prefs, tz) for e in evidences]
        ranked, unverified, excluded = rank(evaluations)
        target_eval = next((e for e in evaluations if requested_id and e.ev.venue.id == requested_id), None)
        if target_eval is not None and target_eval in ranked:
            ranked = [target_eval, *(e for e in ranked if e is not target_eval)]
        mark("ranking", t)

        if ranked:
            status = "ok"
            chosen = ranked[: req.preferences.max_results]
        elif unverified:
            status = "insufficient_data"
            chosen = unverified[: req.preferences.max_results]
        else:
            status = "no_suitable_option"
            chosen = []

        codes = {w.code for w in warnings}
        if "air_missing" not in codes and any(v.best and v.best.cond.us_aqi.value is None for v in chosen):
            warnings.append(WarningItem(type="data_gap", code="air_missing",
                                        message="The air-quality forecast does not cover the recommended time(s); air "
                                                "quality is treated as unknown, not as good.",
                                        evidence_ids=["air:open-meteo"]))

        book = FactBook()
        recs: list[Recommendation] = []
        summaries: list[RecSummary] = []
        requested_start = resolved.requested_clock.replace(minute=0) if resolved.requested_clock else None
        for i, v in enumerate(chosen, start=1):
            best = v.best
            assert best is not None
            prefix = f"R{i}"
            requested = next((s_ for s_ in v.slots if requested_start and s_.slot.start == requested_start), None)
            rf = build_rec_facts(book, prefix, v, best, profile, user, tz, requested)
            alts = alternative_slots(v)
            if requested and requested is not best and requested not in alts:
                alts = [requested, *alts][:3]
            recs.append(Recommendation(
                rank=i, venue=v.ev.venue,
                best_slot=SlotResult(start=best.slot.start, end=best.slot.end, status=best.status, score=best.score,
                                     conditions=best.cond, exclusions=best.safety.exclusions,
                                     cautions=best.safety.cautions + best.safety.gaps),
                alternative_slots=[AlternativeSlot(start=a.slot.start, end=a.slot.end, status=a.status, total=a.total)
                                   for a in alts],
                travel=_travel_info(v.ev.travel),
                context=_context_info(v, best, ctx_features is not None),
                positives=rf.positives, negatives=rf.negatives, advice=rf.advice,
                warnings=best.safety.cautions + best.safety.gaps,
            ))
            slot_text = f"{fmt_time(best.slot.start, tz)}-{fmt_clock(best.slot.end, tz)}"
            summaries.append(RecSummary(prefix, v.ev.venue.display_label, slot_text, best.status, rf))

        general: list[Fact] = []

        def gfact(text: str, ids: list[str]) -> Fact:
            f = Fact(id=f"G{len(general) + 1}", text=text, evidence_ids=ids, numbers=numbers_in(text))
            general.append(f)
            return f

        gfact(f"Searched {n_unique} mapped places within {radius:g} km of {origin.label}; {len(venues)} were evaluated "
              f"across {len(slots)} time slots.", [places_prov.id])
        if target_eval is not None and target_eval not in ranked:
            label = target_eval.ev.venue.display_label
            if target_eval in excluded:
                reasons = summarize_exclusions(target_eval)
                gfact(f"{label}, the place you asked about, has no safe slot in the window"
                      + (f": {reasons[0]}" if reasons else "") + ".", ["derived:engine"])
            else:
                gfact(f"{label}, the place you asked about, could not be verified because key data is missing.",
                      ["derived:engine"])
        if excluded:
            reasons = summarize_exclusions(excluded[0])
            gfact(f"{len(excluded)} place(s) had no safe slot" + (f", e.g. {excluded[0].ev.venue.display_label}: "
                  f"{reasons[0]}" if reasons else "") + ".", ["derived:engine"])
        for w in warnings:
            if w.type == "data_gap" and w.code != "slm_fallback":
                gfact(w.message, w.evidence_ids)
        if user.air_sensitive and status != "no_suitable_option":
            gfact("Air quality comes from a regional model, so local levels near busy roads can be higher than shown.",
                  ["air:open-meteo"])

        message = self._message(status, recs, summaries, profile.label, origin.label, excluded, tz, requested_id)
        response = self._base(
            request_id, now, status, message, interpretation=interpretation, extracted=intent,
            recommendations=recs,
            candidates_considered=[_summary_for(v, chosen) for v in ranked + unverified + excluded],
            timeline=_timeline(ranked + unverified + excluded, slots, chosen, resolved.start, resolved.end, o_series.sun, tz),
            facts=book.facts + general, warnings=warnings, sources=sources, timings_ms=timings,
        )
        if emit:
            await emit("ranking", response.model_dump(mode="json"))

        # 8. Explanation ---------------------------------------------------------------------
        await stage("explaining", "Writing the explanation")
        t = time.monotonic()
        requested_first = bool(requested_id and recs and recs[0].venue.id == requested_id)
        template = template_narrative(summaries, general, status, message, requested_first)
        window_text = f"{fmt_time(resolved.start, tz)} to {fmt_time(resolved.end, tz)} ({tz_name})"
        packet = build_packet(req.question, profile.label, window_text, summaries, book.facts, general,
                              requested_first)
        remaining = s.request_timeout_s - (time.monotonic() - t0) - RESPONSE_MARGIN_S
        narrative: Narrative = await explain(self.slm, packet, book.facts + general, req.question,
                                             [r.prefix for r in summaries], template, s, timeout_s=remaining,
                                             labels={r.prefix: r.label for r in summaries})
        mark("explanation", t)
        timings["total"] = int((time.monotonic() - t0) * 1000)
        response.narrative = narrative
        response.timings_ms = timings
        log_event(logger, "recommendation_done", status=status, activity=activity.value, venues=len(venues),
                  slots=len(slots), parser=result.parser, narrative=narrative.source, timings=timings)
        return response

    def _message(self, status, recs, summaries, label, origin_label, excluded, tz, requested=None) -> str:
        if status == "ok" and summaries:
            r = summaries[0]
            if requested is not None and recs and recs[0].venue.id == requested:
                verdict = "works with some cautions" if r.status == "caution" else "looks suitable"
                return f"{r.label} {verdict} for {label.lower()}; best time {r.slot_text}."
            if requested is not None:
                return (f"The place you asked about did not pass the safety and data checks for that window. Best alternative for "
                        f"{label.lower()} nearby: {r.label}, {r.slot_text}.")
            return f"Best option for {label.lower()} near {origin_label}: {r.label}, {r.slot_text}."
        if status == "insufficient_data" and summaries:
            return ("Some safety-relevant data is missing, so these options could not be fully verified: "
                    f"{summaries[0].label}, {summaries[0].slot_text}.")
        reasons = summarize_exclusions(excluded[0]) if excluded else []
        why = f" Main reason: {reasons[0]}" if reasons else ""
        return f"No place-time combination near {origin_label} passed the safety checks for {label.lower()}.{why}"


# ---------------------------------------------------------------------------- builders
def _candidate(v: Venue, outcome: str, total: float | None, reasons: list[str]) -> CandidateSummary:
    return CandidateSummary(venue_id=v.id, display_label=v.display_label, coords=v.coords, category=v.category,
                            suitability=v.suitability, distance_km=v.distance_km, outcome=outcome, best_total=total,
                            reasons=reasons, osm_url=v.osm_url)


def _summary_for(v: VenueEvaluation, chosen: list[VenueEvaluation]) -> CandidateSummary:
    venue = v.ev.venue
    if v in chosen:
        outcome = "recommended"
    elif v.outcome == "ranked":
        outcome = "ranked"
    elif v.outcome == "unverified":
        outcome = "unverified"
    else:
        outcome = "excluded"
    reasons = summarize_exclusions(v) if outcome == "excluded" else (
        [g.message for g in v.best.safety.gaps] if v.best and outcome == "unverified" else [])
    return _candidate(venue, outcome, v.best.total if v.best else None, reasons)


def _travel_info(t: TravelEvidence | None) -> TravelInfo | None:
    if t is None:
        return None
    src = f"routing:osrm:{t.mode}"
    return TravelInfo(
        mode=t.mode, straight_line_km=t.straight_km,
        route_distance_km=EvidenceValue(value=t.route_km, unit="km", kind="derived", source_id=src) if t.route_km is not None
        else EvidenceValue.unknown("km", "Route distance unavailable", src),
        duration_min=EvidenceValue(value=t.duration_min, unit="min", kind="derived", source_id=src,
                                   note="Free-flow estimate from OSM road network; no live traffic")
        if t.duration_min is not None else EvidenceValue.unknown("min", "Routing unavailable", src),
        note="OSRM free-flow estimate; does not include live traffic." if t.duration_min is not None
        else "Routing unavailable; straight-line distance only.",
    )


def _context_info(v: VenueEvaluation, best, available: bool) -> ContextIndicators | None:
    c = v.ev.context
    src = "context:overpass"
    if c is None:
        return ContextIndicators(
            nearest_major_road_m=EvidenceValue.unknown("m", "Context data unavailable", src),
            green_share_500m=EvidenceValue.unknown("%", "Context data unavailable", src),
            nearest_water_m=EvidenceValue.unknown("m", "Context data unavailable", src),
            status="failed" if not available else "partial")
    flags = []
    if c.nearest_road_m is not None and c.nearest_road_m < 150:
        flags.append(f"Within {c.nearest_road_m:.0f} m of a {c.road_class} road")
    if c.nearest_industrial_m is not None and c.nearest_industrial_m <= 1000:
        flags.append(f"Industrial land use ~{c.nearest_industrial_m:.0f} m away")
    return ContextIndicators(
        nearest_major_road_m=EvidenceValue(value=c.nearest_road_m, unit="m", kind="derived", source_id=src,
                                           note="From venue centre to nearest motorway/trunk/primary/secondary road")
        if c.nearest_road_m is not None else EvidenceValue(value=None, unit="m", kind="derived", source_id=src,
                                                           note="No major road mapped within 1 km"),
        nearest_major_road_class=c.road_class,
        industrial_within_1km=c.nearest_industrial_m is not None and c.nearest_industrial_m <= 1000,
        green_share_500m=EvidenceValue(value=round((c.green_share or 0) * 100, 1), unit="%", kind="derived",
                                       source_id=src, note="Share of a 500 m buffer covered by mapped parks, forest, grass"),
        nearest_water_m=EvidenceValue(value=c.nearest_water_m, unit="m", kind="derived", source_id=src)
        if c.nearest_water_m is not None else EvidenceValue(value=None, unit="m", kind="derived", source_id=src,
                                                            note="No water body mapped within 2 km"),
        upwind_features=best.upwind if best else [],
        flags=flags,
    )


def _timeline(evals: list[VenueEvaluation], slots, chosen, start: datetime, end: datetime, sun, tz) -> Timeline:
    order = chosen + [v for v in evals if v not in chosen]
    rows = []
    for v in order[:8]:
        by_start = {s.slot.start: s for s in v.slots}
        rows.append(TimelineRow(venue_id=v.ev.venue.id, label=v.ev.venue.display_label, cells=[
            TimelineCell(total=by_start[s.start].total if s.start in by_start else None,
                         status=by_start[s.start].status if s.start in by_start else "unverified")  # type: ignore[arg-type]
            for s in slots]))
    series = []
    for v in chosen[:3]:
        series.append(HourlySeries(venue_id=v.ev.venue.id, label=v.ev.venue.display_label,
                                   points=hourly_points(v.ev.weather, v.ev.air, start - timedelta(hours=1),
                                                        min(end, start + timedelta(days=7)))))
    sun_times = [SunTimes(date=d, sunrise=sr, sunset=ss) for d, sr, ss in sun
                 if start.astimezone(tz).date().isoformat() <= d <= end.astimezone(tz).date().isoformat()]
    return Timeline(slot_starts=[s.start for s in slots], rows=rows, series=series, sun=sun_times)

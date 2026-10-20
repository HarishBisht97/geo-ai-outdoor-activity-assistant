import { ExternalLink, MapPin, Minus, Plus, Route, TriangleAlert } from "lucide-react";
import type { Recommendation, ScoreComponent, SlotConditions } from "@/lib/types";
import { COMPONENT_LABEL, cn, fmtRange, fmtTime, fmtValue, scoreColor, titleCase } from "@/lib/format";
import { StatusBadge } from "@/components/common/StatusBadge";
import { ValueBadge } from "@/components/common/ValueBadge";
import { ScoreRing } from "./ScoreRing";

function ComponentBars({ components }: { components: ScoreComponent[] }) {
  return (
    <ul className="space-y-1.5" aria-label="Score breakdown">
      {components.map((c) => (
        <li key={c.name} className="text-xs" title={c.explanation}>
          <div className="flex justify-between">
            <span>{COMPONENT_LABEL[c.name] ?? titleCase(c.name)}</span>
            <span className="tabular-nums text-slate-600">
              {c.score == null ? "unknown" : `${Math.round(c.score * 100)}%`} · weight {Math.round(c.weight * 100)}%
            </span>
          </div>
          <div className="mt-0.5 h-1.5 rounded bg-slate-100">
            {c.score == null ? (
              <div className="h-full rounded border border-dashed border-slate-400" style={{ width: "100%" }} />
            ) : (
              <div className="h-full rounded" style={{ width: `${c.score * 100}%`, background: scoreColor(c.score * 100) }} />
            )}
          </div>
          <p className="mt-0.5 text-[11px] text-slate-500">{c.explanation}</p>
        </li>
      ))}
    </ul>
  );
}

const CONDITION_ROWS: { key: keyof SlotConditions; label: string; digits?: number }[] = [
  { key: "temperature_c", label: "Temperature" },
  { key: "heat_index_c", label: "Heat index" },
  { key: "humidity_pct", label: "Humidity" },
  { key: "precip_probability_pct", label: "Rain chance" },
  { key: "precip_mm", label: "Rain amount", digits: 1 },
  { key: "wind_kmh", label: "Wind" },
  { key: "gust_kmh", label: "Gusts" },
  { key: "uv_index", label: "UV index" },
  { key: "us_aqi", label: "US AQI" },
  { key: "pm2_5", label: "PM2.5" },
];

function ConditionsGrid({ c }: { c: SlotConditions }) {
  return (
    <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs sm:grid-cols-3">
      {CONDITION_ROWS.map(({ key, label, digits }) => {
        const v = c[key] as SlotConditions["temperature_c"];
        return (
          <div key={key} className="flex flex-col rounded bg-slate-50 px-2 py-1">
            <dt className="text-slate-500">{label}</dt>
            <dd className="flex flex-wrap items-center gap-1 font-medium">
              <span className={cn(v.value == null && "italic text-slate-500")}>{fmtValue(v, digits)}</span>
              <ValueBadge kind={v.kind} />
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

export function RecommendationCard({ rec, tz, highlighted }: { rec: Recommendation; tz: string; highlighted?: boolean }) {
  const s = rec.best_slot;
  const v = rec.venue;
  return (
    <article
      aria-labelledby={`rec-${rec.rank}`}
      className={cn("rounded-xl border bg-white p-4 shadow-sm", highlighted ? "border-teal-600 ring-1 ring-teal-600/40" : "border-slate-200")}
    >
      <header className="flex items-start gap-3">
        <ScoreRing total={s.score?.total} />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">#{rec.rank}</p>
          <h3 id={`rec-${rec.rank}`} className="text-lg font-semibold leading-tight">
            {v.display_label}
          </h3>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-slate-600">
            <StatusBadge status={s.status} />
            <span>{fmtRange(s.start, s.end, tz)}</span>
            <span className="inline-flex items-center gap-1">
              <MapPin aria-hidden className="h-3.5 w-3.5" />
              {titleCase(v.category)} · {v.distance_km} km
            </span>
            <span title={v.suitability === "explicit" ? "Mapped facilities match this activity" : "Plausible from mapped tags, facilities not confirmed"}>
              {v.suitability === "explicit" ? "Mapped for this activity" : "Inferred suitability"}
            </span>
          </p>
          {v.suitability_note && <p className="mt-1 text-xs text-slate-500">{v.suitability_note}</p>}
        </div>
      </header>

      {(rec.warnings ?? []).length > 0 && (
        <ul className="mt-3 space-y-1">
          {(rec.warnings ?? []).map((w) => (
            <li key={w.code + w.message} className={cn("flex items-start gap-1.5 rounded px-2 py-1 text-sm", w.type === "avoid" ? "bg-rose-50 text-rose-900" : w.type === "caution" ? "bg-amber-50 text-amber-950" : "bg-slate-50 text-slate-700")}>
              <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                <span className="sr-only">{w.type}: </span>
                {w.message}
              </span>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div>
          {(rec.positives ?? []).length > 0 && (
            <ul className="space-y-1 text-sm" aria-label="In favour">
              {(rec.positives ?? []).map((p) => (
                <li key={p.text} className="flex gap-1.5">
                  <Plus aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" />
                  {p.text}
                </li>
              ))}
            </ul>
          )}
          {(rec.negatives ?? []).length > 0 && (
            <ul className="mt-2 space-y-1 text-sm" aria-label="Against">
              {(rec.negatives ?? []).map((p) => (
                <li key={p.text} className="flex gap-1.5">
                  <Minus aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-rose-700" />
                  {p.text}
                </li>
              ))}
            </ul>
          )}
          {rec.travel && (
            <p className="mt-2 flex items-start gap-1.5 text-sm text-slate-700">
              <Route aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                {rec.travel.duration_min.value != null
                  ? `About ${Math.max(1, Math.round(rec.travel.duration_min.value))} min ${rec.travel.mode}`
                  : `${rec.travel.straight_line_km} km straight-line (route unavailable)`}
                {rec.travel.route_distance_km.value != null ? `, ${rec.travel.route_distance_km.value.toFixed(1)} km` : ""}
                <span className="block text-xs text-slate-500">{rec.travel.note}</span>
              </span>
            </p>
          )}
        </div>
        {s.score && <ComponentBars components={s.score.components} />}
      </div>

      <details className="mt-3">
        <summary className="cursor-pointer text-sm font-medium text-teal-800">Conditions, alternatives and surroundings</summary>
        <div className="mt-2 space-y-3">
          <ConditionsGrid c={s.conditions} />
          {s.score && (
            <p className="text-xs text-slate-500">
              Completeness {Math.round(s.score.completeness * 100)}% · confidence {s.score.confidence}. {s.score.missing_policy}
            </p>
          )}
          {(rec.alternative_slots ?? []).length > 0 && (
            <div>
              <p className="text-sm font-medium">Other times here</p>
              <ul className="mt-1 flex flex-wrap gap-1.5 text-xs">
                {(rec.alternative_slots ?? []).map((a) => (
                  <li key={a.start} className="flex items-center gap-1 rounded border border-slate-200 px-2 py-1">
                    {fmtTime(a.start, tz, { weekday: "short" })} <StatusBadge status={a.status} /> {a.total?.toFixed(0) ?? "–"}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {rec.context && (
            <div className="text-xs text-slate-600">
              <p className="text-sm font-medium text-slate-900">Surroundings</p>
              {rec.context.status === "ok" || rec.context.status === "partial" ? (
                <ul className="list-disc pl-4">
                  <li>Nearest major road: {fmtValue(rec.context.nearest_major_road_m)}{rec.context.nearest_major_road_class ? ` (${rec.context.nearest_major_road_class})` : ""}</li>
                  <li>Green cover within 500 m: {fmtValue(rec.context.green_share_500m)}</li>
                  <li>Industrial land within 1 km: {rec.context.industrial_within_1km == null ? "Unknown" : rec.context.industrial_within_1km ? "yes" : "no"}</li>
                  {(rec.context.upwind_features ?? []).map((u) => (
                    <li key={u}>Upwind: {u}</li>
                  ))}
                </ul>
              ) : (
                <p>Surrounding-feature data was unavailable for this request.</p>
              )}
              <p className="mt-1 italic">{rec.context.note}</p>
            </div>
          )}
          <a href={v.osm_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm text-teal-800 underline">
            View on OpenStreetMap <ExternalLink aria-hidden className="h-3.5 w-3.5" />
          </a>
        </div>
      </details>
    </article>
  );
}

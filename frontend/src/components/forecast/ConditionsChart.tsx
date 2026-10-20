import { CartesianGrid, Legend, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { HourlySeries, SunTimes } from "@/lib/types";
import { fmtTime } from "@/lib/format";

type Props = { series: HourlySeries[]; sun: SunTimes[]; tz: string; venueId?: string };

export function ConditionsChart({ series, sun, tz, venueId }: Props) {
  const row = series.find((s) => s.venue_id === venueId) ?? series[0];
  if (!row) return null;
  const data = row.points.map((p) => ({
    t: p.time,
    heat: p.heat_index_c,
    rain: p.precip_probability_pct,
    aqi: p.us_aqi,
    wind: p.wind_kmh,
  }));
  const nights = sun
    .map((d, i) => {
      const next = sun[i + 1];
      if (!d.sunset) return null;
      return { x1: d.sunset, x2: next?.sunrise ?? data.at(-1)?.t };
    })
    .filter((x): x is { x1: string; x2: string } => Boolean(x?.x2));

  return (
    <section aria-labelledby="cond-h" className="rounded-xl border border-slate-200 bg-white p-3">
      <h3 id="cond-h" className="mb-1 text-sm font-semibold">
        Conditions at {row.label}
      </h3>
      <p className="mb-2 text-[11px] text-slate-500">Heat index (°C), rain chance (%), US AQI and wind (km/h). Grey bands are night.</p>
      <div className="h-56 w-full">
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            {nights.map((n) => (
              <ReferenceArea key={n.x1} x1={n.x1} x2={n.x2} fill="#0f172a" fillOpacity={0.06} />
            ))}
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="t" tickFormatter={(v) => fmtTime(v, tz)} minTickGap={28} tick={{ fontSize: 11 }} />
            <YAxis yAxisId="left" tick={{ fontSize: 11 }} width={32} />
            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} width={32} />
            <Tooltip
              labelFormatter={(v) => fmtTime(String(v), tz, { weekday: "short", day: "numeric", month: "short" })}
              formatter={(value, name) => [value == null ? "Unknown" : Number(value).toFixed(0), String(name)]}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line yAxisId="left" type="monotone" dataKey="heat" name="Heat index °C" stroke="#b45309" dot={false} connectNulls={false} />
            <Line yAxisId="left" type="monotone" dataKey="rain" name="Rain %" stroke="#2563eb" dot={false} connectNulls={false} />
            <Line yAxisId="right" type="monotone" dataKey="aqi" name="US AQI" stroke="#7c3aed" dot={false} connectNulls={false} />
            <Line yAxisId="left" type="monotone" dataKey="wind" name="Wind km/h" stroke="#0f766e" dot={false} connectNulls={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

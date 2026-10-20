import type { Timeline } from "@/lib/types";
import { STATUS_STYLE, fmtTime, scoreColor } from "@/lib/format";

export function ScoreHeatmap({ timeline, tz }: { timeline: Timeline; tz: string }) {
  if (!(timeline.rows ?? []).length) return null;
  return (
    <section aria-labelledby="heat-h" className="overflow-x-auto rounded-xl border border-slate-200 bg-white p-3">
      <h3 id="heat-h" className="mb-2 text-sm font-semibold">
        Score by place and hour
      </h3>
      <table className="w-full min-w-[32rem] border-collapse text-xs">
        <caption className="sr-only">Suitability score for each candidate in each hourly slot. Excluded hours are hatched.</caption>
        <thead>
          <tr>
            <th scope="col" className="sticky left-0 bg-white px-2 py-1 text-left font-medium">
              Place
            </th>
            {(timeline.slot_starts ?? []).map((t) => (
              <th key={t} scope="col" className="px-1 py-1 font-medium text-slate-600">
                {fmtTime(t, tz, { weekday: "short" })}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(timeline.rows ?? []).map((row) => (
            <tr key={row.venue_id}>
              <th scope="row" className="sticky left-0 max-w-[8rem] truncate bg-white px-2 py-1 text-left font-medium">
                {row.label}
              </th>
              {row.cells.map((cell, i) => {
                const hatch = cell.status === "excluded";
                const bg = hatch ? "#fecaca" : scoreColor(cell.total);
                return (
                  <td key={timeline.slot_starts[i]} className="p-0.5">
                    <div
                      title={`${row.label} ${fmtTime(timeline.slot_starts[i], tz)}: ${STATUS_STYLE[cell.status].label}${cell.total != null ? ` ${cell.total.toFixed(0)}` : ""}`}
                      className="flex h-8 items-center justify-center rounded text-[11px] font-semibold tabular-nums text-white"
                      style={{
                        background: hatch
                          ? `repeating-linear-gradient(45deg, ${bg}, ${bg} 4px, #fda4af 4px, #fda4af 8px)`
                          : bg,
                      }}
                    >
                      {cell.total == null ? "–" : cell.total.toFixed(0)}
                      <span className="sr-only"> {STATUS_STYLE[cell.status].label}</span>
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-[11px] text-slate-500">Hatched cells are excluded by a safety filter. Grey is missing evidence, not treated as favourable.</p>
    </section>
  );
}

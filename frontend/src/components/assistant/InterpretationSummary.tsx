import { Bot, ListChecks } from "lucide-react";
import type { RecommendResponse } from "@/lib/types";
import { fmtRange, titleCase } from "@/lib/format";

/** What the assistant understood - every assumption is shown, nothing hidden. */
export function InterpretationSummary({ response }: { response: RecommendResponse }) {
  const i = response.interpretation;
  if (!i) return null;
  const tz = i.window.timezone;
  return (
    <details className="rounded-lg border border-slate-200 bg-white p-3 text-sm" open={(i.assumptions ?? []).length > 0}>
      <summary className="flex cursor-pointer items-center gap-2 font-medium">
        <ListChecks aria-hidden className="h-4 w-4 text-teal-700" />
        I understood: {titleCase(i.activity)}
        {i.activity_detail ? ` (${i.activity_detail})` : ""} near {i.origin.label}, {fmtRange(i.window.start, i.window.end, tz)}
      </summary>
      <dl className="mt-2 grid grid-cols-[auto,1fr] gap-x-4 gap-y-1 text-slate-700">
        <dt className="text-slate-500">Radius</dt>
        <dd>{i.radius_km} km</dd>
        <dt className="text-slate-500">Duration</dt>
        <dd>{i.duration_minutes} min</dd>
        <dt className="text-slate-500">Travel</dt>
        <dd>{titleCase(i.travel_mode)}</dd>
        <dt className="text-slate-500">Timezone</dt>
        <dd>{tz}</dd>
        {(i.sensitivities ?? []).length > 0 && (
          <>
            <dt className="text-slate-500">Considerations</dt>
            <dd>{(i.sensitivities ?? []).map(titleCase).join(", ")}</dd>
          </>
        )}
        {(i.group?.children || i.group?.elderly) && (
          <>
            <dt className="text-slate-500">Group</dt>
            <dd>{[i.group.children && "children", i.group.elderly && "older adults"].filter(Boolean).join(", ")}</dd>
          </>
        )}
        <dt className="text-slate-500">Read by</dt>
        <dd className="inline-flex items-center gap-1">
          <Bot aria-hidden className="h-3.5 w-3.5" />
          {i.parser === "slm" ? `${response.model.base_model} (${response.model.quantization})` : "keyword rules (fallback)"}
        </dd>
      </dl>
      {(i.assumptions ?? []).length > 0 && (
        <>
          <p className="mt-2 font-medium">Assumptions</p>
          <ul className="list-disc pl-5 text-slate-700">
            {(i.assumptions ?? []).map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </>
      )}
    </details>
  );
}

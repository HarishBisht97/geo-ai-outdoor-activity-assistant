import { Check, Loader2 } from "lucide-react";
import type { StageEvent } from "@/lib/types";
import { cn } from "@/lib/format";

export const STAGES: { id: string; label: string }[] = [
  { id: "understanding", label: "Understanding the question" },
  { id: "locating", label: "Finding the starting point" },
  { id: "finding_places", label: "Searching OpenStreetMap for places" },
  { id: "fetching_conditions", label: "Fetching forecasts, air quality and routes" },
  { id: "ranking", label: "Comparing places and times" },
  { id: "explaining", label: "Writing the explanation" },
];

/** Driven only by real `stage` events from the backend stream. */
export function ProgressSteps({ events, finished }: { events: StageEvent[]; finished: boolean }) {
  const seen = new Map(events.map((e) => [e.stage, e]));
  const lastIdx = Math.max(-1, ...STAGES.map((s, i) => (seen.has(s.id) ? i : -1)));
  return (
    <ol aria-label="Progress" aria-live="polite" className="space-y-1.5 text-sm">
      {STAGES.map((s, i) => {
        const done = finished ? seen.has(s.id) : i < lastIdx;
        const active = !finished && i === lastIdx;
        const ev = seen.get(s.id);
        return (
          <li key={s.id} className={cn("flex items-start gap-2", !done && !active && "text-slate-400")}>
            <span className="mt-0.5 flex h-4 w-4 items-center justify-center">
              {done ? (
                <Check aria-hidden className="h-4 w-4 text-teal-700" />
              ) : active ? (
                <Loader2 aria-hidden className="h-4 w-4 animate-spin text-teal-700" />
              ) : (
                <span aria-hidden className="h-2 w-2 rounded-full bg-slate-300" />
              )}
            </span>
            <span>
              <span className={cn(active && "font-semibold")}>{s.label}</span>
              {ev?.detail && (active || done) ? <span className="block text-xs text-slate-500">{ev.detail}</span> : null}
              <span className="sr-only">{done ? " (done)" : active ? " (in progress)" : " (pending)"}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

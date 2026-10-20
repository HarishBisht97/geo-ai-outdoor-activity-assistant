import { useQuery } from "@tanstack/react-query";
import { ChevronDown, History } from "lucide-react";
import { useMemo, useState } from "react";
import { ClarificationPanel } from "@/components/assistant/ClarificationPanel";
import { InterpretationSummary } from "@/components/assistant/InterpretationSummary";
import { ProgressSteps } from "@/components/assistant/ProgressSteps";
import { DataGapBanner, ErrorState, RecordedBanner } from "@/components/common/Banners";
import { SourcesDrawer } from "@/components/evidence/SourcesDrawer";
import { ConditionsChart } from "@/components/forecast/ConditionsChart";
import { ScoreHeatmap } from "@/components/forecast/ScoreHeatmap";
import { AttributionFooter } from "@/components/layout/AttributionFooter";
import { ResultsMap } from "@/components/map/ResultsMap";
import { BestPick } from "@/components/recommendations/BestPick";
import { ActivityChips } from "@/components/search/ActivityChips";
import { AdjustPanel, EMPTY_ADJUSTMENTS, toPreferences, type Adjustments } from "@/components/search/AdjustPanel";
import { ExampleQueries } from "@/components/search/ExampleQueries";
import { QueryBox } from "@/components/search/QueryBox";
import { getReady } from "@/lib/api";
import { useAssistant } from "@/hooks/useAssistant";
import type { IntentOverrides, RecommendResponse } from "@/lib/types";

const RECORDED = [
  { name: "powai-running", label: "Running near Powai (21 Oct 2026)" },
  { name: "cubbon-picnic", label: "Picnic in Cubbon Park (21 Oct 2026)" },
];

export default function App() {
  const [question, setQuestion] = useState("");
  const [activity, setActivity] = useState<NonNullable<IntentOverrides["activity"]> | null>(null);
  const [adjust, setAdjust] = useState<Adjustments>(EMPTY_ADJUSTMENTS);
  const [showAdjust, setShowAdjust] = useState(false);
  const { state, ask, answer, retry, loadRecorded, reset } = useAssistant();
  const ready = useQuery({ queryKey: ["ready"], queryFn: () => getReady(), refetchInterval: 30_000 });

  const shown: RecommendResponse | null = state.response ?? state.ranking;
  const tz = shown?.interpretation?.window.timezone ?? "UTC";
  const overrides = useMemo<IntentOverrides | null>(() => (activity ? { activity } : null), [activity]);
  const busy = state.phase === "running";

  function submit(q = question) {
    const text = q.trim();
    if (text.length < 3) return;
    setQuestion(text);
    void ask(text, toPreferences(adjust), overrides);
  }

  function useLocationFromClarify() {
    if (!("geolocation" in navigator)) return;
    navigator.geolocation.getCurrentPosition((pos) => {
      answer({
        field: "location",
        value: { origin: { lat: +pos.coords.latitude.toFixed(4), lon: +pos.coords.longitude.toFixed(4), label: "Your location" } },
      });
    });
  }

  return (
    <div className="min-h-screen">
      {state.recorded && <RecordedBanner capturedAt={state.recorded.capturedAt} onExit={reset} />}
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl flex-wrap items-end justify-between gap-3 px-4 py-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-teal-800">GeoAI Hackathon · CSRE, IIT Bombay</p>
            <h1 className="text-2xl font-bold tracking-tight">Outdoor activity assistant</h1>
            <p className="mt-1 max-w-xl text-sm text-slate-600">
              Best nearby place and time from live OpenStreetMap, Open-Meteo and OSRM data. A 1.7B model on this server reads the question and explains the ranking — never invents venues.
            </p>
          </div>
          <p className="text-xs text-slate-500" aria-live="polite">
            {ready.isError
              ? "API unreachable"
              : ready.data?.status === "ready"
                ? ready.data.slm_enabled
                  ? "Server ready, model loaded"
                  : "Server ready (keyword parser)"
                : ready.data?.status === "loading"
                  ? "Model still loading — answers use keyword rules until then"
                  : ready.data
                    ? "Server degraded — keyword rules in use"
                    : "Checking server…"}
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-5 px-4 py-6">
        <QueryBox value={question} onChange={setQuestion} onSubmit={() => submit()} busy={busy} />
        <ExampleQueries
          disabled={busy}
          onPick={(q) => {
            setQuestion(q);
            submit(q);
          }}
        />
        <ActivityChips value={activity} onChange={setActivity} />
        <button
          type="button"
          onClick={() => setShowAdjust((v) => !v)}
          className="inline-flex items-center gap-1 text-sm text-slate-600 underline"
        >
          <ChevronDown aria-hidden className={`h-4 w-4 transition ${showAdjust ? "rotate-180" : ""}`} />
          Radius, travel, health and time
        </button>
        {showAdjust && <AdjustPanel value={adjust} onChange={setAdjust} />}

        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <History aria-hidden className="h-3.5 w-3.5" />
          Recorded live sessions:
          {RECORDED.map((r) => (
            <button key={r.name} type="button" onClick={() => loadRecorded(r.name)} className="rounded-full border border-slate-300 px-2 py-0.5 hover:border-teal-600">
              {r.label}
            </button>
          ))}
        </div>

        {busy && (
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <ProgressSteps events={state.stages} finished={false} />
          </div>
        )}

        {state.error && <ErrorState error={state.error} onRetry={retry} />}

        {shown && (
          <div className="space-y-4">
            {state.phase === "running" && state.ranking && !state.response && (
              <p className="rounded-md bg-teal-50 px-3 py-2 text-sm text-teal-900">Ranking is ready. Writing the explanation…</p>
            )}
            <InterpretationSummary response={shown} />
            <DataGapBanner warnings={shown.warnings ?? []} />
            {shown.status === "needs_clarification" && shown.clarification && (
              <ClarificationPanel clarification={shown.clarification} onAnswer={answer} onUseLocation={useLocationFromClarify} />
            )}
            {shown.status === "no_suitable_option" && (
              <p className="rounded-lg border border-slate-300 bg-slate-50 p-3">{shown.message}</p>
            )}
            {shown.status === "insufficient_data" && (
              <p className="rounded-lg border border-amber-300 bg-amber-50 p-3">{shown.message}</p>
            )}
            {((shown.recommendations ?? []).length > 0 || (shown.candidates_considered ?? []).length > 0) && (
              <>
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Places</h2>
                  <SourcesDrawer response={shown} />
                </div>
                <ResultsMap response={shown} />
                {(shown.recommendations ?? []).length > 0 && <BestPick response={shown} />}
                {shown.timeline && (
                  <>
                    <ScoreHeatmap timeline={shown.timeline} tz={tz} />
                    <ConditionsChart
                      series={shown.timeline.series ?? []}
                      sun={shown.timeline.sun ?? []}
                      tz={tz}
                      venueId={shown.recommendations?.[0]?.venue.id}
                    />
                  </>
                )}
              </>
            )}
          </div>
        )}
      </main>
      <AttributionFooter response={shown} />
    </div>
  );
}

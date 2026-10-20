import { Backpack, Bot, Eye, FileText, PauseCircle, Sparkles } from "lucide-react";
import type { Narrative, NarrativeItem, RecommendResponse } from "@/lib/types";
import { RecommendationCard } from "./RecommendationCard";

function Items({ title, items, Icon }: { title: string; items: NarrativeItem[]; Icon: typeof Eye }) {
  if (!items.length) return null;
  return (
    <div>
      <h4 className="flex items-center gap-1.5 text-sm font-semibold">
        <Icon aria-hidden className="h-4 w-4 text-teal-700" /> {title}
      </h4>
      <ul className="mt-1 list-disc space-y-0.5 pl-6 text-sm text-slate-700">
        {items.map((i) => (
          <li key={i.text}>{i.text}</li>
        ))}
      </ul>
    </div>
  );
}

function NarrativeSource({ n }: { n: Narrative }) {
  const label =
    n.source === "slm"
      ? "Written by the on-server language model from the evidence below"
      : n.source === "mixed"
        ? "Language-model text checked against the evidence; unsupported parts replaced by templates"
        : "Generated from deterministic templates";
  return (
    <p className="flex items-center gap-1.5 text-xs text-slate-500">
      {n.source === "template" ? <FileText aria-hidden className="h-3.5 w-3.5" /> : <Bot aria-hidden className="h-3.5 w-3.5" />}
      {label}
      {n.removed_claims > 0 ? ` · ${n.removed_claims} unsupported statement(s) removed` : ""}
    </p>
  );
}

export function BestPick({ response }: { response: RecommendResponse }) {
  const tz = response.interpretation?.window.timezone ?? "UTC";
  const [best, ...rest] = response.recommendations ?? [];
  const n = response.narrative;
  return (
    <section aria-labelledby="best-h" className="space-y-4">
      {n && (
        <div className="rounded-xl border border-teal-200 bg-teal-50/60 p-4">
          <h2 id="best-h" className="flex items-center gap-2 text-lg font-semibold text-teal-950">
            <Sparkles aria-hidden className="h-5 w-5" /> {n.summary?.text ?? response.message}
          </h2>
          {n.best && <p className="mt-2 text-slate-800">{n.best.text}</p>}
          {n.alternative && <p className="mt-1 text-slate-700">{n.alternative.text}</p>}
          {(n.why ?? []).length > 0 && (
            <ul className="mt-2 list-disc space-y-0.5 pl-6 text-sm text-slate-700">
              {(n.why ?? []).map((w) => (
                <li key={w.text}>{w.text}</li>
              ))}
            </ul>
          )}
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <Items title="Carry" items={n.carry ?? []} Icon={Backpack} />
            <Items title="Watch for" items={n.watch_for ?? []} Icon={Eye} />
            <Items title="Postpone if" items={n.postpone_if ?? []} Icon={PauseCircle} />
          </div>
          {(n.caveats ?? []).length > 0 && (
            <ul className="mt-3 space-y-0.5 text-xs text-slate-600">
              {(n.caveats ?? []).map((c) => (
                <li key={c.text}>Note: {c.text}</li>
              ))}
            </ul>
          )}
          <div className="mt-3">
            <NarrativeSource n={n} />
          </div>
        </div>
      )}
      {!n && (
        <h2 id="best-h" className="text-lg font-semibold">
          {response.message}
        </h2>
      )}
      {best && <RecommendationCard rec={best} tz={tz} highlighted />}
      {rest.length > 0 && (
        <div className="space-y-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Alternatives</h3>
          {rest.map((r) => (
            <RecommendationCard key={r.venue.id} rec={r} tz={tz} />
          ))}
        </div>
      )}
    </section>
  );
}

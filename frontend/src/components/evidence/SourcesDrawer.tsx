import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { Fact, Provenance, RecommendResponse } from "@/lib/types";
import { ValueBadge } from "@/components/common/ValueBadge";
import { titleCase } from "@/lib/format";

function SourceRow({ s }: { s: Provenance }) {
  return (
    <article className="rounded-lg border border-slate-200 p-3 text-sm">
      <header className="flex flex-wrap items-center gap-2">
        <h4 className="font-semibold">{s.provider}</h4>
        <ValueBadge kind={s.data_kind} />
        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs uppercase">{s.status}</span>
        {s.cache_hit && <span className="text-xs text-slate-500">served from cache</span>}
      </header>
      <p className="mt-1 text-xs text-slate-500">
        Retrieved {new Date(s.retrieved_at).toUTCString()}
        {s.issued_at ? ` · issued ${new Date(s.issued_at).toUTCString()}` : ""}
        {s.license ? ` · ${s.license}` : ""}
      </p>
      {s.attribution && <p className="mt-1 text-xs">{s.attribution}</p>}
      {s.error && <p className="mt-1 text-xs text-rose-800">{s.error}</p>}
      {(s.limitations ?? []).length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-xs text-slate-600">
          {(s.limitations ?? []).map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}
      {s.url && (
        <a href={s.url} target="_blank" rel="noreferrer" className="mt-1 inline-block break-all text-xs text-teal-800 underline">
          Query URL
        </a>
      )}
    </article>
  );
}

function Facts({ facts }: { facts: Fact[] }) {
  if (!facts.length) return null;
  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-sm font-medium">Evidence facts used in the explanation</summary>
      <ul className="mt-2 space-y-1 text-xs">
        {facts.map((f) => (
          <li key={f.id}>
            <code className="mr-1 rounded bg-slate-100 px-1">{f.id}</code>
            {f.text}
          </li>
        ))}
      </ul>
    </details>
  );
}

export function SourcesDrawer({ response }: { response: RecommendResponse }) {
  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button type="button" className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm hover:border-teal-600 focus-visible:outline-2 focus-visible:outline-teal-700">
          Sources and evidence
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[2000] bg-black/40" />
        <Dialog.Content className="fixed inset-y-0 right-0 z-[2001] flex w-full max-w-lg flex-col bg-white shadow-xl focus:outline-none">
          <header className="flex items-center justify-between border-b px-4 py-3">
            <Dialog.Title className="font-semibold">Where every value came from</Dialog.Title>
            <Dialog.Close aria-label="Close" className="rounded p-1 hover:bg-slate-100">
              <X className="h-5 w-5" />
            </Dialog.Close>
          </header>
          <div className="flex-1 space-y-3 overflow-y-auto p-4">
            <p className="text-sm text-slate-600">
              Engine {response.engine_version} · rules {response.rules_version} · request {response.request_id}
              {response.data_mode === "fixture" ? " · recorded fixture (not live)" : " · live fetch"}
            </p>
            {(response.data_quality ?? []).map((d) => (
              <p key={d.provider} className="text-xs text-slate-600">
                <strong>{d.provider}</strong> ({titleCase(d.purpose)}): {d.status}
                {d.message ? ` — ${d.message}` : ""}
              </p>
            ))}
            {(response.sources ?? []).map((s) => (
              <SourceRow key={s.id} s={s} />
            ))}
            <Facts facts={response.facts ?? []} />
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

import { AlertCircle, History, Info, RefreshCw } from "lucide-react";
import type { ApiError } from "@/lib/api";
import type { WarningItem } from "@/lib/types";

export function DataGapBanner({ warnings }: { warnings: WarningItem[] }) {
  const gaps = warnings.filter((w) => w.type === "data_gap");
  if (!gaps.length) return null;
  return (
    <section aria-label="Data gaps" className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
      <h3 className="mb-1 flex items-center gap-1.5 font-semibold">
        <Info aria-hidden className="h-4 w-4" /> Some data was missing or limited
      </h3>
      <ul className="list-disc space-y-0.5 pl-5">
        {gaps.map((g) => (
          <li key={g.code + g.message}>{g.message}</li>
        ))}
      </ul>
    </section>
  );
}

export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-rose-300 bg-rose-50 p-4 text-rose-950">
      <p className="flex items-center gap-2 font-semibold">
        <AlertCircle aria-hidden className="h-5 w-5" /> {error.message}
      </p>
      <p className="mt-1 text-xs text-rose-800">
        Code: {error.code}
        {error.requestId ? ` · request ${error.requestId}` : ""}
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-rose-700 px-3 py-1.5 text-sm font-medium text-white hover:bg-rose-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-700"
        >
          <RefreshCw aria-hidden className="h-4 w-4" /> Retry
        </button>
      )}
    </div>
  );
}

export function RecordedBanner({ capturedAt, onExit }: { capturedAt: string; onExit: () => void }) {
  const when = new Date(capturedAt).toUTCString();
  return (
    <div role="status" className="sticky top-0 z-[1000] flex flex-wrap items-center justify-between gap-2 bg-indigo-700 px-4 py-2 text-sm text-white">
      <span className="flex items-center gap-2">
        <History aria-hidden className="h-4 w-4" />
        <strong>Recorded session</strong> - a real live response captured {when}. Conditions shown are not current.
      </span>
      <button type="button" onClick={onExit} className="rounded bg-white/15 px-2 py-1 font-medium hover:bg-white/25">
        Back to live
      </button>
    </div>
  );
}

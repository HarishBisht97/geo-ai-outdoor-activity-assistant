import { HelpCircle, MapPin } from "lucide-react";
import { useState, type FormEvent } from "react";
import type { Clarification, ClarificationOption } from "@/lib/types";

type Answer = ClarificationOption | { field: string; value: Record<string, unknown> };

const FREE_TEXT: Record<string, { label: string; key: string; placeholder: string }> = {
  location: { label: "Starting area, landmark or city", key: "location_text", placeholder: "e.g. Koregaon Park, Pune" },
  destination: { label: "Destination", key: "destination_text", placeholder: "e.g. Hinjewadi Phase 1" },
};

/** Form built from the response's missing_fields and options; answers are sent as structured overrides. */
export function ClarificationPanel({
  clarification,
  onAnswer,
  onUseLocation,
}: {
  clarification: Clarification;
  onAnswer: (a: Answer) => void;
  onUseLocation?: () => void;
}) {
  const [text, setText] = useState<Record<string, string>>({});
  const freeFields = clarification.missing_fields.filter((f) => FREE_TEXT[f]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const value: Record<string, unknown> = {};
    for (const f of freeFields) {
      const v = (text[f] ?? "").trim();
      if (v) value[FREE_TEXT[f].key] = v;
    }
    if (Object.keys(value).length) onAnswer({ field: freeFields.join(","), value });
  }

  return (
    <section aria-labelledby="clarify-h" className="rounded-lg border border-sky-300 bg-sky-50 p-4">
      <h2 id="clarify-h" className="mb-2 flex items-center gap-2 font-semibold text-sky-950">
        <HelpCircle aria-hidden className="h-5 w-5" /> A little more detail is needed
      </h2>
      <ul className="mb-3 space-y-1 text-sky-950">
        {clarification.questions.map((q) => (
          <li key={q}>{q}</li>
        ))}
      </ul>

      {(clarification.options ?? []).length > 0 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {(clarification.options ?? []).map((o) => (
            <button
              key={o.label}
              type="button"
              onClick={() => onAnswer(o)}
              className="rounded-md border border-sky-400 bg-white px-3 py-1.5 text-left text-sm hover:bg-sky-100 focus-visible:outline-2 focus-visible:outline-sky-700"
            >
              {o.label}
            </button>
          ))}
        </div>
      )}

      {freeFields.length > 0 && (
        <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row sm:items-end">
          {freeFields.map((f) => (
            <label key={f} className="flex flex-1 flex-col text-sm">
              <span className="mb-1 font-medium">{FREE_TEXT[f].label}</span>
              <input
                value={text[f] ?? ""}
                maxLength={120}
                onChange={(e) => setText({ ...text, [f]: e.target.value })}
                placeholder={FREE_TEXT[f].placeholder}
                className="rounded-md border border-slate-300 px-3 py-2"
              />
            </label>
          ))}
          <button type="submit" className="rounded-md bg-sky-800 px-4 py-2 font-medium text-white hover:bg-sky-900">
            Continue
          </button>
          {clarification.missing_fields.includes("location") && onUseLocation && (
            <button type="button" onClick={onUseLocation} className="inline-flex items-center gap-1 rounded-md border border-sky-400 bg-white px-3 py-2 text-sm">
              <MapPin aria-hidden className="h-4 w-4" /> Use my location
            </button>
          )}
        </form>
      )}
    </section>
  );
}

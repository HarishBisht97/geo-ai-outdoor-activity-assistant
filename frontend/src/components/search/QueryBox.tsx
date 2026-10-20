import { Loader2, Search } from "lucide-react";
import type { FormEvent } from "react";

type Props = {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  busy: boolean;
};

export function QueryBox({ value, onChange, onSubmit, busy }: Props) {
  const tooShort = value.trim().length < 3;
  function submit(e: FormEvent) {
    e.preventDefault();
    if (!tooShort && !busy) onSubmit();
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row" role="search">
      <label htmlFor="question" className="sr-only">
        Your question
      </label>
      <textarea
        id="question"
        rows={2}
        maxLength={500}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) submit(e);
        }}
        placeholder="e.g. Where can I go running tomorrow evening near Koregaon Park?"
        className="min-h-[3.25rem] flex-1 resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-base shadow-sm focus:border-teal-600 focus:outline-none focus:ring-2 focus:ring-teal-600/30"
      />
      <button
        type="submit"
        disabled={tooShort || busy}
        className="inline-flex items-center justify-center gap-2 rounded-lg bg-teal-700 px-5 py-2.5 font-semibold text-white shadow-sm hover:bg-teal-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : <Search aria-hidden className="h-4 w-4" />}
        {busy ? "Working…" : "Find"}
      </button>
    </form>
  );
}

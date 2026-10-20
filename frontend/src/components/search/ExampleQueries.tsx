export const EXAMPLES = [
  "Where can I go running tomorrow evening near Koregaon Park?",
  "What is the best time this weekend for a children's cricket match within 15 km of Whitefield?",
  "I have mild asthma. Where is suitable for a morning walk near Powai over the next two days?",
  "Is it a good idea to cycle to work at 8 AM?",
  "Where should I organize an outdoor birthday party on Sunday afternoon?",
  "What is the best time and place for hiking near Lonavala?",
  "Where can my elderly parents walk outside tomorrow?",
  "Where can I take sunset photographs this evening?",
];

export function ExampleQueries({ onPick, disabled }: { onPick: (q: string) => void; disabled?: boolean }) {
  return (
    <div>
      <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">Try an example</p>
      <ul className="flex flex-wrap gap-1.5">
        {EXAMPLES.map((q) => (
          <li key={q}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onPick(q)}
              className="rounded-full border border-slate-300 bg-white px-3 py-1 text-left text-sm text-slate-700 hover:border-teal-600 hover:text-teal-800 focus-visible:outline-2 focus-visible:outline-teal-700 disabled:opacity-50"
            >
              {q}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

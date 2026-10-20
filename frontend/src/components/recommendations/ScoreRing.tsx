import { scoreColor } from "@/lib/format";

export function ScoreRing({ total, size = 64 }: { total: number | null | undefined; size?: number }) {
  const r = size / 2 - 5;
  const c = 2 * Math.PI * r;
  const pct = total == null ? 0 : Math.max(0, Math.min(100, total)) / 100;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={total == null ? "No score" : `Score ${total.toFixed(0)} out of 100`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#e2e8f0" strokeWidth={6} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={scoreColor(total)}
        strokeWidth={6}
        strokeLinecap="round"
        strokeDasharray={`${c * pct} ${c}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text x="50%" y="50%" dominantBaseline="central" textAnchor="middle" className="fill-slate-900 text-base font-bold">
        {total == null ? "–" : total.toFixed(0)}
      </text>
    </svg>
  );
}

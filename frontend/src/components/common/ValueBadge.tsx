import { Calculator, CircleHelp, CloudSun, Cpu, Eye } from "lucide-react";
import type { DataKind } from "@/lib/types";
import { cn } from "@/lib/format";

const KIND: Record<DataKind, { label: string; title: string; Icon: typeof CloudSun; cls: string }> = {
  forecast: { label: "Forecast", title: "Numerical weather model forecast", Icon: CloudSun, cls: "border-sky-300 bg-sky-50 text-sky-900" },
  modeled: { label: "Modeled", title: "Regional atmospheric model estimate (not a local measurement)", Icon: Cpu, cls: "border-violet-300 bg-violet-50 text-violet-900" },
  observed: { label: "Mapped", title: "From OpenStreetMap or another observed source", Icon: Eye, cls: "border-teal-300 bg-teal-50 text-teal-900" },
  derived: { label: "Derived", title: "Computed by the engine from other values", Icon: Calculator, cls: "border-slate-300 bg-slate-50 text-slate-800" },
  unknown: { label: "Unknown", title: "No data available - not treated as favourable", Icon: CircleHelp, cls: "border-dashed border-slate-400 bg-white text-slate-600" },
};

/** Value-kind badge: icon + text, never colour alone. */
export function ValueBadge({ kind, className }: { kind: DataKind; className?: string }) {
  const k = KIND[kind] ?? KIND.unknown;
  return (
    <span
      title={k.title}
      className={cn("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11px] font-medium leading-none", k.cls, className)}
    >
      <k.Icon aria-hidden className="h-3 w-3" />
      {k.label}
    </span>
  );
}

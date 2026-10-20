import { AlertTriangle, Ban, CheckCircle2, HelpCircle } from "lucide-react";
import type { SlotStatus } from "@/lib/types";
import { STATUS_STYLE, cn } from "@/lib/format";

const ICON = { suitable: CheckCircle2, caution: AlertTriangle, unverified: HelpCircle, excluded: Ban };

export function StatusBadge({ status, className }: { status: SlotStatus; className?: string }) {
  const s = STATUS_STYLE[status];
  const Icon = ICON[status];
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1", s.cls, className)}>
      <Icon aria-hidden className="h-3.5 w-3.5" />
      {s.label}
    </span>
  );
}

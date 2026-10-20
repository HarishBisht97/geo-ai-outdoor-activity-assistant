import { Bike, Camera, CircleDot, Flag, Footprints, Mountain, PartyPopper, Trophy, TreePine, Volleyball } from "lucide-react";
import type { IntentOverrides } from "@/lib/types";
import { cn } from "@/lib/format";

type Activity = NonNullable<IntentOverrides["activity"]>;

export const ACTIVITIES: { id: Activity; label: string; Icon: typeof Bike }[] = [
  { id: "running", label: "Running", Icon: Footprints },
  { id: "cycling", label: "Cycling", Icon: Bike },
  { id: "golf", label: "Golf", Icon: Flag },
  { id: "cricket", label: "Cricket", Icon: Trophy },
  { id: "football", label: "Football", Icon: Volleyball },
  { id: "tennis", label: "Tennis", Icon: CircleDot },
  { id: "hiking", label: "Hiking / walk", Icon: Mountain },
  { id: "picnic", label: "Picnic", Icon: TreePine },
  { id: "outdoor_event", label: "Outdoor event", Icon: PartyPopper },
  { id: "photography", label: "Photography", Icon: Camera },
];

/** Optional explicit activity; when set it is sent as an override and wins over text extraction. */
export function ActivityChips({ value, onChange }: { value: Activity | null; onChange: (a: Activity | null) => void }) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate-500">Activity (optional)</legend>
      <div className="flex flex-wrap gap-1.5">
        {ACTIVITIES.map(({ id, label, Icon }) => {
          const on = value === id;
          return (
            <button
              key={id}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(on ? null : id)}
              className={cn(
                "inline-flex items-center gap-1 rounded-md border px-2 py-1 text-sm focus-visible:outline-2 focus-visible:outline-teal-700",
                on ? "border-teal-700 bg-teal-700 text-white" : "border-slate-300 bg-white text-slate-700 hover:border-teal-600",
              )}
            >
              <Icon aria-hidden className="h-3.5 w-3.5" />
              {label}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

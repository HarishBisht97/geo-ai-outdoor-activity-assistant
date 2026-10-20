import * as Slider from "@radix-ui/react-slider";
import { LocateFixed, X } from "lucide-react";
import { useState } from "react";
import type { Preferences, Sensitivity, TravelMode } from "@/lib/types";
import { cn } from "@/lib/format";

export type Adjustments = {
  radiusKm: number | null;
  travelMode: TravelMode | null;
  sensitivities: Sensitivity[];
  origin: { lat: number; lon: number; label: string } | null;
  windowStart: string; // datetime-local
  windowEnd: string;
};

export const EMPTY_ADJUSTMENTS: Adjustments = {
  radiusKm: null,
  travelMode: null,
  sensitivities: [],
  origin: null,
  windowStart: "",
  windowEnd: "",
};

function withOffset(local: string): string {
  // datetime-local has no zone: attach the browser's current UTC offset explicitly
  const d = new Date(local);
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  const hh = String(Math.floor(Math.abs(off) / 60)).padStart(2, "0");
  const mm = String(Math.abs(off) % 60).padStart(2, "0");
  return `${local.length === 16 ? `${local}:00` : local}${sign}${hh}:${mm}`;
}

export function toPreferences(a: Adjustments): Preferences {
  const p: Preferences = { max_results: 3 };
  if (a.radiusKm) p.radius_km = a.radiusKm;
  if (a.travelMode) p.travel_mode = a.travelMode;
  if (a.sensitivities.length) p.sensitivities = a.sensitivities;
  if (a.origin) p.origin = a.origin;
  if (a.windowStart && a.windowEnd) p.time_window = { start: withOffset(a.windowStart), end: withOffset(a.windowEnd) };
  return p;
}

const SENS: { id: Sensitivity; label: string }[] = [
  { id: "respiratory", label: "Asthma / breathing" },
  { id: "heat_sensitive", label: "Heat-sensitive" },
  { id: "limited_mobility", label: "Limited mobility" },
];
const MODES: { id: TravelMode; label: string }[] = [
  { id: "walking", label: "Walk" },
  { id: "cycling", label: "Cycle" },
  { id: "driving", label: "Drive" },
];

export function AdjustPanel({ value, onChange }: { value: Adjustments; onChange: (a: Adjustments) => void }) {
  const [geoMsg, setGeoMsg] = useState<string | null>(null);
  const set = (patch: Partial<Adjustments>) => onChange({ ...value, ...patch });

  function useMyLocation() {
    if (!("geolocation" in navigator)) {
      setGeoMsg("Location is not available in this browser.");
      return;
    }
    setGeoMsg("Requesting your location…");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        set({ origin: { lat: +pos.coords.latitude.toFixed(4), lon: +pos.coords.longitude.toFixed(4), label: "Your location" } });
        setGeoMsg(null);
      },
      () => setGeoMsg("Location permission was not granted."),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 },
    );
  }

  return (
    <div className="grid gap-4 rounded-lg border border-slate-200 bg-white p-4 text-sm sm:grid-cols-2">
      <div>
        <label id="radius-label" className="mb-2 block font-medium">
          Search radius: {value.radiusKm ? `${value.radiusKm} km` : "activity default"}
        </label>
        <div className="flex items-center gap-3">
          <Slider.Root
            aria-labelledby="radius-label"
            className="relative flex h-5 flex-1 touch-none select-none items-center"
            min={1}
            max={50}
            step={1}
            value={[value.radiusKm ?? 10]}
            onValueChange={([v]) => set({ radiusKm: v })}
          >
            <Slider.Track className="relative h-1.5 grow rounded-full bg-slate-200">
              <Slider.Range className="absolute h-full rounded-full bg-teal-600" />
            </Slider.Track>
            <Slider.Thumb aria-label="Radius in km" className="block h-4 w-4 rounded-full border-2 border-teal-700 bg-white focus-visible:outline-2 focus-visible:outline-teal-700" />
          </Slider.Root>
          {value.radiusKm && (
            <button type="button" onClick={() => set({ radiusKm: null })} className="text-xs text-slate-500 underline">
              reset
            </button>
          )}
        </div>
      </div>

      <fieldset>
        <legend className="mb-2 font-medium">Travel mode</legend>
        <div className="flex gap-1.5">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              aria-pressed={value.travelMode === m.id}
              onClick={() => set({ travelMode: value.travelMode === m.id ? null : m.id })}
              className={cn(
                "rounded-md border px-2.5 py-1 focus-visible:outline-2 focus-visible:outline-teal-700",
                value.travelMode === m.id ? "border-teal-700 bg-teal-700 text-white" : "border-slate-300 hover:border-teal-600",
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="mb-2 font-medium">Health considerations (not stored)</legend>
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          {SENS.map((s) => (
            <label key={s.id} className="inline-flex items-center gap-1.5">
              <input
                type="checkbox"
                className="h-4 w-4 accent-teal-700"
                checked={value.sensitivities.includes(s.id)}
                onChange={(e) =>
                  set({
                    sensitivities: e.target.checked
                      ? [...value.sensitivities, s.id]
                      : value.sensitivities.filter((x) => x !== s.id),
                  })
                }
              />
              {s.label}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="mb-2 font-medium">Time window (optional, your local time)</legend>
        <div className="flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="win-start">From</label>
          <input id="win-start" type="datetime-local" value={value.windowStart} onChange={(e) => set({ windowStart: e.target.value })} className="rounded border border-slate-300 px-2 py-1" />
          <span aria-hidden>–</span>
          <label className="sr-only" htmlFor="win-end">To</label>
          <input id="win-end" type="datetime-local" value={value.windowEnd} onChange={(e) => set({ windowEnd: e.target.value })} className="rounded border border-slate-300 px-2 py-1" />
        </div>
      </fieldset>

      <div className="sm:col-span-2">
        {value.origin ? (
          <p className="inline-flex items-center gap-2 rounded-md bg-teal-50 px-2 py-1 text-teal-900">
            <LocateFixed aria-hidden className="h-4 w-4" /> Starting from your location ({value.origin.lat}, {value.origin.lon})
            <button type="button" aria-label="Stop using my location" onClick={() => set({ origin: null })}>
              <X className="h-4 w-4" />
            </button>
          </p>
        ) : (
          <button type="button" onClick={useMyLocation} className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-2.5 py-1 hover:border-teal-600">
            <LocateFixed aria-hidden className="h-4 w-4" /> Use my location
          </button>
        )}
        <p className="mt-1 text-xs text-slate-500">
          {geoMsg ?? "Only used for this request, rounded to about 10 m, and never stored."}
        </p>
      </div>
    </div>
  );
}

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { EvidenceValue, SlotStatus } from "./types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Times are shown in the location's timezone (from the response), never the browser's. */
export function fmtTime(iso: string, tz: string, opts: Intl.DateTimeFormatOptions = {}): string {
  return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: tz, ...opts }).format(
    new Date(iso),
  );
}

export function fmtDay(iso: string, tz: string): string {
  return new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: tz }).format(
    new Date(iso),
  );
}

export function fmtRange(start: string, end: string, tz: string): string {
  return `${fmtDay(start, tz)}, ${fmtTime(start, tz)}–${fmtTime(end, tz)}`;
}

const UNIT_LABEL: Record<string, string> = {
  degC: "°C",
  C: "°C",
  "%": "%",
  "km/h": " km/h",
  mm: " mm",
  m: " m",
  km: " km",
  min: " min",
  deg: "°",
  "ug/m3": " µg/m³",
  US_AQI: "",
  index: "",
  wmo: "",
};

export function fmtValue(v: EvidenceValue | null | undefined, digits = 0): string {
  if (!v || v.value === null || v.value === undefined) return "Unknown";
  const unit = UNIT_LABEL[v.unit] ?? ` ${v.unit}`;
  return `${v.value.toFixed(digits)}${unit}`;
}

export const STATUS_STYLE: Record<SlotStatus, { label: string; cls: string }> = {
  suitable: { label: "Suitable", cls: "bg-emerald-100 text-emerald-900 ring-emerald-600/30" },
  caution: { label: "Caution", cls: "bg-amber-100 text-amber-900 ring-amber-600/30" },
  unverified: { label: "Unverified", cls: "bg-slate-200 text-slate-800 ring-slate-500/30" },
  excluded: { label: "Excluded", cls: "bg-rose-100 text-rose-900 ring-rose-600/30" },
};

export function scoreColor(total: number | null | undefined): string {
  if (total === null || total === undefined) return "#94a3b8";
  if (total >= 75) return "#047857";
  if (total >= 55) return "#65a30d";
  if (total >= 35) return "#d97706";
  return "#b91c1c";
}

export const COMPONENT_LABEL: Record<string, string> = {
  thermal: "Heat & temperature",
  air_quality: "Air quality",
  precipitation: "Rain",
  wind: "Wind",
  uv: "UV",
  daylight: "Daylight",
  travel: "Travel time",
  surface: "Ground (recent rain)",
  visibility: "Visibility",
  context: "Surroundings (roads, industry, green)",
  sky: "Sky",
  golden_hour: "Golden-hour light",
  space: "Open space",
  venue_fit: "Venue fit",
};

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

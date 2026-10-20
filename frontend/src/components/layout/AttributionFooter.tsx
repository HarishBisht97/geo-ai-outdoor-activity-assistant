import type { RecommendResponse } from "@/lib/types";

export function AttributionFooter({ response }: { response?: RecommendResponse | null }) {
  const lines = response?.attribution ?? [
    "Map data (c) OpenStreetMap contributors, ODbL 1.0",
    "Weather and air-quality data by Open-Meteo.com (CC BY 4.0); air quality from Copernicus CAMS",
    "Routing by OSRM on OpenStreetMap data",
    "Geocoding by Nominatim (OpenStreetMap)",
  ];
  return (
    <footer className="mt-10 border-t border-slate-200 bg-white px-4 py-6 text-xs text-slate-600">
      <p className="mx-auto max-w-5xl font-medium text-slate-800">Attribution</p>
      <ul className="mx-auto mt-1 max-w-5xl list-disc space-y-0.5 pl-5">
        {lines.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
      <p className="mx-auto mt-3 max-w-5xl italic">
        {response?.disclaimer ??
          "Recommendations are generated from public forecasts, modelled air quality and OpenStreetMap data, which can be wrong or incomplete. They are not medical advice."}
      </p>
    </footer>
  );
}

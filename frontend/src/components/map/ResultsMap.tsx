import { Circle, CircleMarker, MapContainer, Popup, TileLayer, useMap } from "react-leaflet";
import { useEffect } from "react";
import type { CandidateSummary, RecommendResponse } from "@/lib/types";
import { StatusBadge } from "@/components/common/StatusBadge";
import "leaflet/dist/leaflet.css";

const COLOR: Record<CandidateSummary["outcome"], string> = {
  recommended: "#0f766e",
  ranked: "#2563eb",
  excluded: "#be123c",
  unverified: "#64748b",
};

function Fit({ response }: { response: RecommendResponse }) {
  const map = useMap();
  useEffect(() => {
    const pts: [number, number][] = [];
    const o = response.interpretation?.origin;
    if (o) pts.push([o.lat, o.lon]);
    for (const c of response.candidates_considered ?? []) pts.push([c.coords.lat, c.coords.lon]);
    if (pts.length === 1) map.setView(pts[0], 13);
    else if (pts.length > 1) map.fitBounds(pts, { padding: [28, 28], maxZoom: 14 });
  }, [map, response]);
  return null;
}

export function ResultsMap({ response }: { response: RecommendResponse }) {
  const origin = response.interpretation?.origin;
  const center: [number, number] = origin ? [origin.lat, origin.lon] : [20.6, 78.9];
  const recById = new Map((response.recommendations ?? []).map((r) => [r.venue.id, r]));
  return (
    <figure className="overflow-hidden rounded-xl border border-slate-200">
      <MapContainer center={center} zoom={12} className="h-[360px] w-full" scrollWheelZoom={false} attributionControl>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Fit response={response} />
        {origin && (
          <>
            <CircleMarker center={[origin.lat, origin.lon]} radius={7} pathOptions={{ color: "#111827", fillColor: "#111827", fillOpacity: 1 }}>
              <Popup>Start: {origin.label}</Popup>
            </CircleMarker>
            <Circle
              center={[origin.lat, origin.lon]}
              radius={(response.interpretation?.radius_km ?? 5) * 1000}
              pathOptions={{ color: "#0f766e", weight: 1, fillOpacity: 0.04 }}
            />
          </>
        )}
        {(response.candidates_considered ?? []).map((c) => {
          const rec = recById.get(c.venue_id);
          return (
            <CircleMarker
              key={c.venue_id}
              center={[c.coords.lat, c.coords.lon]}
              radius={c.outcome === "recommended" ? 9 : 6}
              pathOptions={{ color: COLOR[c.outcome], fillColor: COLOR[c.outcome], fillOpacity: 0.85, weight: 2 }}
            >
              <Popup>
                <strong>{c.display_label}</strong>
                <div className="mt-1 text-xs">
                  {c.category} · {c.distance_km} km · {c.outcome}
                  {c.best_total != null ? ` · ${c.best_total.toFixed(0)}` : ""}
                </div>
                {rec && <StatusBadge status={rec.best_slot.status} className="mt-1" />}
                {c.reasons?.[0] && <p className="mt-1 text-xs">{c.reasons[0]}</p>}
                <a href={c.osm_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs underline">
                  OpenStreetMap
                </a>
              </Popup>
            </CircleMarker>
          );
        })}
      </MapContainer>
      <figcaption className="flex flex-wrap gap-3 bg-white px-3 py-1.5 text-xs text-slate-600">
        {(["recommended", "ranked", "excluded", "unverified"] as const).map((k) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: COLOR[k] }} aria-hidden />
            {k}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-full bg-gray-900" aria-hidden /> start
        </span>
      </figcaption>
    </figure>
  );
}

# Data sources

All sources are free, require no paid key, and are recorded in every response under `sources[]` with retrieved_at, license, URL (no secrets), cache_hit, status and limitations. Production `data_mode` is always `live`.

| Id | Provider | Purpose | License | Limit we honour |
| --- | --- | --- | --- | --- |
| `geocode:nominatim` | Nominatim | Place-name → lat/lon | ODbL 1.0 | 1 req/s, identifying User-Agent, 7-day cache |
| `places:overpass` | Overpass | Activity-tagged venues + context | ODbL 1.0 | Fair use; three mirrors; 24 h cache |
| `places:nominatim` | Nominatim search | Venue fallback when Overpass is slow | ODbL 1.0 | 1 req/s, 40 results/tag |
| `weather:open-meteo` | Open-Meteo forecast | Hourly weather, sunrise/sunset | CC BY 4.0 | Non-commercial < 10k/day; 30 min cache |
| `air:open-meteo` | Open-Meteo AQ (CAMS) | PM2.5, PM10, US AQI | CC BY 4.0 | ~5 day, regional grid; 60 min cache |
| `elevation:open-meteo` | Open-Meteo elevation | Hiking / photography | CC BY 4.0 | 100 coords/call |
| `routing:osrm` | OSRM public + FOSSGIS | Free-flow duration/distance | ODbL (OSM) | Demo servers, no live traffic |

User-Agent is `GeoAI-Outdoor-Assistant/0.1 (+CONTACT_EMAIL)`. Set `CONTACT_EMAIL` in production.

## Provenance and value kinds

Every displayed number is an `EvidenceValue`: `{value, unit, kind, valid_time, source_id, note}`. Kinds:

- **Forecast** — Open-Meteo numerical weather model.
- **Modeled** — CAMS regional air quality, not a local measurement.
- **Observed** — OSM tags / Nominatim.
- **Derived** — heat index, travel minutes, green-share, upwind flag.
- **Unknown** — missing; never scored as favourable.

## Known operational issues

Public Overpass is often slow or returns 502. The pipeline starts a Nominatim POI search after 10 s (`places_hedge_after_s`) and prefers Overpass if it finishes within 20 s. Surrounding-feature context is skipped after 12 s so the request stays inside the 90 s budget; the fetch keeps running to warm the cache.

OSRM is free-flow from the OSM network. The UI always shows “no live traffic”.

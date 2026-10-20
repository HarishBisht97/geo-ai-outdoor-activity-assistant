# Architecture

The backend is a FastAPI modular monolith. One process loads one GGUF. Ranking is deterministic Python; the SLM is a sidecar that may time out without breaking the answer.

```
Browser
  │  POST /api/v1/recommend/stream
  ▼
FastAPI ── rate limit (10/min) ── in-flight semaphore
  │
  ├─ SLM intent (grammar JSON) ─┬─ keyword parser (always)
  │                             └─ reconcile (location span, activity/day tokens)
  ├─ Nominatim geocode (clarify if ambiguous; urban preference for name clashes)
  ├─ Overpass venue search ── hedge after 10 s → Nominatim POI fallback
  ├─ Open-Meteo weather + CAMS air quality (batched cells) + OSRM table
  ├─ Safety filters (per slot) THEN component scores THEN rank + tie-break
  ├─ SSE `ranking` event (UI can render)
  └─ SLM explanation (grammar JSON) → claim validator → template fill
```

## Modules (`backend/app`)

| Package | Responsibility |
| --- | --- |
| `api/` | HTTP, CORS, error envelope, SSE, health/ready |
| `core/` | Settings, shared httpx client, per-host throttle, JSON logs, rate limit |
| `cache/` | TTL cache with in-flight coalescing; failures are never cached |
| `services/` | Nominatim, Overpass, Open-Meteo, OSRM adapters; provenance on every fetch |
| `geo/` | OSM tag registry, parse/dedupe, azimuthal-equidistant context, wind-upwind |
| `ranking/` | Thresholds, activity profiles, safety, curves, slots, deterministic ranker |
| `slm/` | llama.cpp runtime, prompts, intent, evidence packet, validator, templates |
| `orchestration/` | Pipeline, clarification, time resolution |
| `schemas/` | Pydantic request/response; OpenAPI is generated from these |

## Time and place

Relative phrases (“tomorrow morning”, “this weekend”, “in 10 days”) become absolute windows in the **location’s IANA timezone**. Times in the API and UI are never converted to the browser’s zone. Past windows and windows beyond the 7-day forecast raise typed errors and become clarification.

## Failure policy

Missing weather → slot `unverified` (critical gap). Missing AQI → unknown, not “good”; air-sensitive users get `unverified`. Overpass timeout → Nominatim fallback + `places_fallback` warning. SLM timeout/invalid JSON → keyword parser / template narrative + `slm_fallback` warning. The response always names the parser and the narrative `source` (`slm` / `template` / `mixed`).

## Versions

`API_VERSION=v1`, `ENGINE_VERSION=0.1.0`, `RULES_VERSION=2026.10.1`, `PROMPT_VERSION=2026-10-20.3`.

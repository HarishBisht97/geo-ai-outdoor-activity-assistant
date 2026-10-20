# GeoAI Outdoor Activity Recommendation Assistant

Finds the **best nearby place and time** for an outdoor activity from **live** OpenStreetMap, Open-Meteo and OSRM data. A deterministic engine applies safety filters **before** scoring. A self-hosted **Qwen3-1.7B** (GGUF, llama.cpp, CPU) reads the question and explains the ranking. It never invents venues or numbers.

Built for the GeoAI Hackathon at CSRE, IIT Bombay.

- **API (this repo):** FastAPI, deployed as a Hugging Face Docker Space.
- **UI:** Vite + React + TypeScript + Tailwind, Leaflet map, recorded-session replay.
- **Model:** [`Qwen/Qwen3-1.7B`](https://huggingface.co/Qwen/Qwen3-1.7B) revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`, 2.03B params, Apache-2.0, Q4_K_M GGUF.

## Quick start (local, no model)

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp ../.env.example .env
# leave SLM_ENABLED unset or set false to use the keyword parser
uvicorn app.main:app --reload --port 7860
```

```bash
cd frontend
pnpm i
cp .env.example .env   # VITE_API_BASE_URL=http://localhost:7860
pnpm dev               # http://localhost:5173
```

Recorded live answers (no API): on the home page, click **Running near Powai** or **Picnic in Cubbon Park**.

## Quick start (with the SLM)

```bash
cd backend
pip install -r requirements-slm.txt          # llama-cpp-python (Metal on macOS)
# place Qwen3-1.7B-Q4_K_M.gguf in backend/models/
SLM_ENABLED=true MODEL_PATH=models/Qwen3-1.7B-Q4_K_M.gguf \
  uvicorn app.main:app --port 7860 --workers 1
```

A live query typically takes 20–80 s on a laptop CPU (intent + OSM/weather + explanation), inside a 90 s budget.

## What it will and will not do

**Will:** geocode the named place (or ask which one), search OSM for activity-tagged venues, fetch hourly weather and US AQI, score every place×hour after safety exclusions, stream ranking before the explanation, show provenance for every value.

**Will not:** guess a location you did not name, treat missing AQI as “good air”, claim live traffic, give medical advice, or keep health flags after the request.

## API

| Method | Path | Notes |
| --- | --- | --- |
| POST | `/api/v1/recommend` | Synchronous, 90 s budget |
| POST | `/api/v1/recommend/stream` | SSE: `stage` → `ranking` → `done` |
| GET | `/api/v1/activities`, `/api/v1/sources` | Rule registry and data-source list |
| GET | `/health`, `/ready` | Liveness; model loaded (no outbound probes) |
| GET | `/docs` | OpenAPI |

Request: `{ "question": "Where can I go running tomorrow morning near Powai?", "preferences": { "radius_km": 10 } }`.

Errors: `{ "error": { "code", "message", "request_id", "details?" } }`. Rate limit 10 requests/minute/IP.

## Tests

```bash
cd backend && python -m pytest            # unit + e2e replay (no network)
python -m pytest -m live                  # opt-in, hits real APIs
cd ../frontend && pnpm test && pnpm build
```

## Layout

```
backend/app          FastAPI app, ranking engine, SLM runtime, OSM/weather adapters
backend/tests        Unit, API, 17 required e2e cases, recorded HTTP sessions
frontend/           React UI (types generated from frontend/openapi.json)
hf_model/           Model card, prompts, quantize.sh, eval results
docs/               Architecture, data sources, scoring, API, deployment
slides/deck.md      5-slide Marp deck
space/README.md     Hugging Face Space card
```

## Docs

- [Architecture](docs/architecture.md)
- [Data sources](docs/data-sources.md)
- [Scoring rules](docs/scoring-rules.md)
- [API](docs/api.md)
- [Deployment](docs/deployment.md)

## Attribution

Map data (c) OpenStreetMap contributors, ODbL 1.0. Weather and air quality by [Open-Meteo](https://open-meteo.com) (CC BY 4.0); air quality from Copernicus CAMS. Routing by OSRM on OSM data. Geocoding by Nominatim. Language model: Qwen3-1.7B (Alibaba / Qwen, Apache-2.0).

Recommendations are not medical advice. Forecasts and modelled air quality can be wrong; check conditions on site.

## License

Application code: MIT. Model weights: Apache-2.0 (Qwen3).

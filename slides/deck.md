---
marp: true
theme: default
paginate: true
title: GeoAI Outdoor Activity Assistant
---

# Best place **and** time, from live maps and weather
**GeoAI Outdoor Activity Recommendation Assistant** · CSRE, IIT Bombay

Self-hosted **Qwen3-1.7B** (2.03B, Apache-2.0, GGUF Q4_K_M, llama.cpp on CPU) reads the question and explains the ranking. A **deterministic engine** searches OpenStreetMap, scores Open-Meteo forecasts and CAMS air quality, and applies safety filters **before** scoring. No hosted LLM. No invented venues.

---

# What a request actually does

1. **Understand** — grammar-constrained JSON; keyword parser always cross-checks; missing location → ask, never guess.
2. **Find real places** — Overpass activity tags, Nominatim fallback if Overpass is slow; named parks (Cubbon Park) are evaluated as venues.
3. **Fetch live conditions** — hourly weather, US AQI, free-flow OSRM travel. Every value has a source, time and kind (forecast / modeled / derived / unknown).
4. **Filter then rank** — thunder, heat, gusts, AQI tiers exclude slots; missing AQI is unknown, not “good air”.
5. **Explain** — the model only describes R1/R2 using numbered facts; numbers and names are validated; advice is a template.

Typical CPU latency 60–80 s (budget 90 s). Ranking streams to the UI first.

---

# Ten activities, safety-first scoring

Running, cycling, golf, cricket, football, tennis, hiking / nature walk, picnic, outdoor events, photography.

| Gate | Source |
| --- | --- |
| Heat index 41 °C strenuous | NWS |
| US AQI 201 everyone; 151 sensitive; 101 sensitive + strenuous | EPA |
| Gusts to activity limit / 62 km/h gale | Beaufort |
| Thunder (WMO 95/96/99) ± buffer | NWS |

Score: weighted components × completeness penalty (missing evidence never helps). Tie-break: margin, travel, distance, id — bit-stable.

---

# Evidence the judges can audit

- **Provenance** on every fetch: URL, retrieved_at, license, cache hit, limitations.
- **Value-kind badges** in the UI (icon + text, not colour alone).
- **Recorded sessions** on the site (Powai running, Cubbon picnic) with a persistent “not live” banner.
- **17 e2e cases** replay recorded HTTP: happy path, AQI, heat, thunder, unsupported activity, SLM timeout / malformed JSON, Overpass failure.
- Intent eval (60 questions): **activity 97%, location 100%, JSON valid 100%, p50 7.9 s**.

---

# Run it

**API** Hugging Face Docker Space, CPU Basic, weights baked at image build.  
**UI** Vercel (or the Space serves `frontend/dist`).  
**Model repo** GGUF + prompts + this card, Apache-2.0.

```
POST /api/v1/recommend/stream
{ "question": "Where can I go running tomorrow morning near Powai?" }
```

OpenStreetMap (ODbL) · Open-Meteo / CAMS (CC BY 4.0) · OSRM · Qwen3-1.7B (Apache-2.0).  
Not medical advice. Check conditions on site.

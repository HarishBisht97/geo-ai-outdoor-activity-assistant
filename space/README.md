---
title: GeoAI Outdoor Assistant API
emoji: 🏃
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Place-time outdoor activity recommendations with a self-hosted SLM
---

# GeoAI Outdoor Assistant - API Space

This Space runs the FastAPI backend of the
[GeoAI Outdoor Activity Assistant](https://github.com/HarishBisht97/geo-ai-outdoor-activity-assistant).

- `POST /api/v1/recommend` - synchronous recommendation
- `POST /api/v1/recommend/stream` - Server-Sent Events with progress, ranking, then narrative
- `GET /health`, `GET /ready`, `GET /docs`

The language model (Qwen3-1.7B, GGUF Q4_K_M, Apache-2.0) is downloaded at image build time and executed
in-process with llama.cpp on this Space's CPU. No hosted inference API is used.

Data: (c) OpenStreetMap contributors (ODbL), Open-Meteo (CC BY 4.0), OSRM routing on OSM data.

This directory's contents are synced to the Space root together with `backend/` by
`.github/workflows/deploy-space.yml`.

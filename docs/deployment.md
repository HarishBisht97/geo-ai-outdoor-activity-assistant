# Deployment

## Hugging Face Space (API)

- SDK: Docker, port **7860**, hardware **CPU Basic**.
- Image (`backend/Dockerfile`): builds a portable `llama-cpp-python` wheel (`GGML_NATIVE=OFF`), downloads the GGUF at **build** time so restarts do not re-download, runs `uvicorn --workers 1`.
- Env: `MODEL_PATH=/models/Qwen3-1.7B-Q4_K_M.gguf`, `N_THREADS=2`, `N_CTX=4096`, `APP_ENV=production`, `ALLOWED_ORIGINS=<Vercel origin>`.
- Workflow: `.github/workflows/deploy-space.yml` uploads `backend/app`, `Dockerfile`, requirements and `space/README.md` when `vars.HF_SPACE` and `secrets.HF_TOKEN` are set.
- Keepalive: `.github/workflows/keepalive.yml` GETs `/health` every 6 hours (`vars.SPACE_URL`).

If `backend/static/index.html` exists, FastAPI also serves the built UI (single-origin fallback). Copy `frontend/dist` there after `pnpm build`.

## Vercel (frontend)

- Root: `frontend/`. Framework Vite. Env `VITE_API_BASE_URL=https://<space>.hf.space`.
- CORS: add the Vercel origin to `ALLOWED_ORIGINS` on the Space.

## Local Docker

```bash
cd backend
docker build -t geoai-api .
docker run --rm -p 7860:7860 -e CONTACT_EMAIL=you@example.com geoai-api
```

First build downloads ~1.1 GB GGUF.

## Latency (laptop CPU, 2 threads, 2026-10-20)

| Stage | Typical |
| --- | --- |
| Intent (Q4_K_M, warm) | 4–9 s (eval p50 7.9 s, p95 14.3 s) |
| Places + weather + routes | 10–25 s (Overpass hedge at 10 s) |
| Explanation | ~20–25 s, 250–290 tokens |
| **End-to-end** | **~60–80 s**, budget 90 s |

Space CPU Basic is similar or slower; `/ready` and the keepalive cron reduce cold starts. The UI shows ranking as soon as the `ranking` event arrives.

## What you still need credentials for

These are **not** in the repo. Nothing secrets-shaped is logged.

| Secret / var | Where | Purpose |
| --- | --- | --- |
| `HF_TOKEN` | GitHub Actions | Push the Space and (optional) the model repo |
| `vars.HF_SPACE` | GitHub | e.g. `username/geoai-outdoor-assistant` |
| `vars.SPACE_URL` | GitHub | Keepalive URL |
| Vercel project + `VITE_API_BASE_URL` | Vercel | Frontend origin |
| `CONTACT_EMAIL` | Space env | Nominatim/Overpass User-Agent |
| `ALLOWED_ORIGINS` | Space env | CORS allowlist |

Optional: `python hf_model/publish.py --repo <user>/geoai-outdoor-qwen3-1.7b-gguf` with `HF_TOKEN` to publish the GGUF + model card.

`OPENAQ_API_KEY` is unused in v1 (CAMS via Open-Meteo is the air source).

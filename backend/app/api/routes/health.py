from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app import API_VERSION, ENGINE_VERSION
from app.api.state import AppServices, services

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness")
async def health(svc: AppServices = Depends(services)) -> dict:
    return {"status": "ok", "uptime_s": int(time.monotonic() - svc.started_at), "version": ENGINE_VERSION}


@router.get("/ready", summary="Readiness: model loaded and last-known provider status (no active probing)")
async def ready(svc: AppServices = Depends(services)):
    info = svc.slm.info()
    slm_ok = bool(info.get("loaded")) or not svc.settings.slm_enabled
    body = {
        "ready": slm_ok,
        "status": "ready" if slm_ok else ("loading" if svc.model_loading else "degraded"),
        "api_version": API_VERSION,
        "model": {k: v for k, v in info.items() if k != "load_error"} | (
            {"load_error": "model failed to load"} if info.get("load_error") else {}),
        "slm_enabled": svc.settings.slm_enabled,
        "cache": svc.cache.stats(),
        "providers_last_seen": svc.provider_status,
        "note": "When the model is not loaded, requests are still served using rule-based parsing and template text.",
    }
    return JSONResponse(body, status_code=200 if slm_ok else 503)

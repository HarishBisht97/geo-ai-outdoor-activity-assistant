from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import API_VERSION, ENGINE_VERSION
from app.api.routes import health, meta, recommend
from app.api.state import AppServices
from app.cache.ttl_cache import AsyncTTLCache
from app.core.config import Settings, get_settings
from app.core.errors import AppError, OverloadedError
from app.core.http import HttpClient
from app.core.logging import configure_logging, log_event, request_id_var
from app.core.ratelimit import SlidingWindowLimiter
from app.orchestration.recommendation_pipeline import Pipeline
from app.services.base import ServiceDeps
from app.slm.prompts import INTENT_SCHEMA, INTENT_SYSTEM, intent_user_prompt
from app.slm.runtime import DisabledRuntime, LlamaCppRuntime, TextGenerator

logger = logging.getLogger("app")
RID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


async def _load_model(svc: AppServices) -> None:
    rt = svc.slm
    if not isinstance(rt, LlamaCppRuntime):
        return
    svc.model_loading = True
    try:
        await asyncio.to_thread(rt.load)
        if rt.is_loaded:
            await rt.warmup(INTENT_SYSTEM, intent_user_prompt("Where can I go running tomorrow morning?"),
                            INTENT_SCHEMA)
    finally:
        svc.model_loading = False


def create_app(
    settings: Settings | None = None,
    *,
    transport=None,
    slm: TextGenerator | None = None,
    data_mode: str = "live",
    clock=None,
) -> FastAPI:
    """App factory. `transport`, `slm` and `clock` are injection points for tests only."""
    settings = settings or get_settings()
    if data_mode != "live" and settings.app_env != "test":
        raise RuntimeError("Fixture data mode is only allowed when APP_ENV=test")
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cache = AsyncTTLCache()
        http = HttpClient(settings.user_agent, timeout_s=settings.http_timeout_s, retries=settings.http_retries,
                          transport=transport, throttle=settings.http_throttle or settings.app_env != "test")
        runtime: TextGenerator = slm or (LlamaCppRuntime(settings) if settings.slm_enabled else DisabledRuntime())
        deps = ServiceDeps(settings=settings, http=http, cache=cache)
        pipeline = Pipeline(settings, deps, runtime, data_mode=data_mode, clock=clock)
        svc = AppServices(settings=settings, http=http, cache=cache, slm=runtime, pipeline=pipeline,
                          limiter=SlidingWindowLimiter(settings.rate_limit_per_min),
                          semaphore=asyncio.Semaphore(settings.max_concurrent_requests))
        app.state.services = svc
        load_task = asyncio.create_task(_load_model(svc))
        log_event(logger, "startup", env=settings.app_env, slm_enabled=settings.slm_enabled, data_mode=data_mode)
        yield
        load_task.cancel()
        await http.aclose()

    app = FastAPI(
        title="GeoAI Outdoor Activity Assistant API",
        version=ENGINE_VERSION,
        description=(
            "Recommends the best nearby place **and** time for outdoor activities using live OpenStreetMap, "
            "Open-Meteo and OSRM data, a deterministic safety-first ranking engine, and a self-hosted "
            "Qwen3-1.7B small language model (llama.cpp) for question understanding and explanations.\n\n"
            f"API version: `{API_VERSION}`. Map data (c) OpenStreetMap contributors (ODbL)."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins or ["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if RID_RE.match(incoming) else uuid.uuid4().hex[:16]
        request_id_var.set(rid)
        start = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        log_event(logger, "http_request", method=request.method, path=request.url.path,
                  status=response.status_code, ms=int((time.monotonic() - start) * 1000))
        return response

    def envelope(code: str, message: str, status: int, details: dict | None = None, headers: dict | None = None):
        body = {"error": {"code": code, "message": message, "request_id": request_id_var.get(), "details": details}}
        return JSONResponse(body, status_code=status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return envelope("validation_error", "The request is invalid.", 422, {"errors": errors})

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        headers = None
        retry = exc.details.get("retry_after_s") if exc.details else None
        if retry:
            headers = {"Retry-After": str(retry)}
        return envelope(exc.code, exc.message, exc.status_code, exc.details or None, headers)

    @app.exception_handler(OverloadedError)
    async def _overloaded(_: Request, exc: OverloadedError):
        return envelope(exc.code, exc.message, 503, exc.details, {"Retry-After": str(exc.retry_after_s)})

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("unhandled error")
        return envelope("internal_error", "Unexpected server error.", 500)

    @app.get("/", include_in_schema=False)
    async def root():
        index = _frontend_dist() / "index.html"
        if index.is_file():
            return FileResponse(index)
        return {"name": "GeoAI Outdoor Activity Assistant API", "docs": "/docs", "health": "/health",
                "ready": "/ready", "recommend": "POST /api/v1/recommend"}

    app.include_router(health.router)
    app.include_router(recommend.router)
    app.include_router(meta.router)
    dist = _frontend_dist()
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="ui")
    return app


def _frontend_dist() -> Path:
    return Path(__file__).resolve().parents[1] / "static"


app = create_app()

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from fastapi import Request

from app.cache.ttl_cache import AsyncTTLCache
from app.core.config import Settings
from app.core.http import HttpClient
from app.core.ratelimit import SlidingWindowLimiter
from app.orchestration.recommendation_pipeline import Pipeline
from app.schemas.common import Provenance
from app.slm.runtime import TextGenerator


@dataclass
class AppServices:
    settings: Settings
    http: HttpClient
    cache: AsyncTTLCache
    slm: TextGenerator
    pipeline: Pipeline
    limiter: SlidingWindowLimiter
    semaphore: asyncio.Semaphore
    started_at: float = field(default_factory=time.monotonic)
    model_loading: bool = False
    provider_status: dict[str, dict] = field(default_factory=dict)

    def record_sources(self, sources: list[Provenance]) -> None:
        for p in sources:
            if p.id == "derived:engine":
                continue
            self.provider_status[p.provider] = {"status": p.status, "at": p.retrieved_at.isoformat(), "error": p.error}


def services(request: Request) -> AppServices:
    return request.app.state.services


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

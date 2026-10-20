from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Generic, TypeVar

from app.cache.ttl_cache import AsyncTTLCache
from app.core.config import Settings
from app.core.http import HttpClient
from app.schemas.common import DataKind, Provenance, SourceStatus

T = TypeVar("T")

OSM_ATTRIBUTION = "(c) OpenStreetMap contributors, ODbL 1.0"
OPEN_METEO_ATTRIBUTION = "Weather data by Open-Meteo.com, CC BY 4.0"


@dataclass
class Fetched(Generic[T]):
    data: T | None
    provenance: Provenance

    @property
    def ok(self) -> bool:
        return self.data is not None and self.provenance.status in ("ok", "partial")


@dataclass
class ServiceDeps:
    settings: Settings
    http: HttpClient
    cache: AsyncTTLCache
    extra: dict = field(default_factory=dict)


_background: set[asyncio.Task] = set()


def keep_running(task: asyncio.Task) -> None:
    """Let a no-longer-awaited fetch finish in the background so its result reaches the cache."""
    _background.add(task)
    task.add_done_callback(_background.discard)
    task.add_done_callback(lambda t: t.cancelled() or t.exception())


def now_utc() -> datetime:
    return datetime.now(UTC)


def make_provenance(
    pid: str,
    provider: str,
    *,
    url: str | None,
    kind: DataKind,
    license: str | None,
    attribution: str | None,
    cache_hit: bool = False,
    status: SourceStatus = "ok",
    limitations: list[str] | None = None,
    error: str | None = None,
    retrieved_at: datetime | None = None,
) -> Provenance:
    return Provenance(
        id=pid,
        provider=provider,
        url=url,
        retrieved_at=retrieved_at or now_utc(),
        data_kind=kind,
        license=license,
        attribution=attribution,
        cache_hit=cache_hit,
        status=status,
        limitations=limitations or [],
        error=error,
    )


def round_coord(v: float, step: float = 0.02) -> float:
    return round(round(v / step) * step, 4)

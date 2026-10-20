from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DataKind = Literal["forecast", "modeled", "observed", "derived", "unknown"]
SourceStatus = Literal["ok", "partial", "failed", "stale", "skipped"]


class Coordinates(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Provenance(BaseModel):
    id: str = Field(description="Stable id referenced by evidence values, e.g. 'weather:open-meteo'")
    provider: str
    url: str | None = Field(default=None, description="Query URL without secrets")
    retrieved_at: datetime
    issued_at: datetime | None = None
    data_kind: DataKind
    license: str | None = None
    attribution: str | None = None
    cache_hit: bool = False
    status: SourceStatus = "ok"
    limitations: list[str] = Field(default_factory=list)
    error: str | None = None


class EvidenceValue(BaseModel):
    value: float | None
    unit: str
    kind: DataKind
    valid_time: datetime | None = None
    source_id: str | None = None
    note: str | None = None

    @classmethod
    def unknown(cls, unit: str, note: str, source_id: str | None = None) -> "EvidenceValue":
        return cls(value=None, unit=unit, kind="unknown", note=note, source_id=source_id)


class WarningItem(BaseModel):
    type: Literal["data_gap", "caution", "avoid"]
    code: str
    message: str
    evidence_ids: list[str] = Field(default_factory=list)

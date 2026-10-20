"""Overpass API client with mirror rotation and caching.

Fair use: ~10k queries/day and 2 concurrent slots per IP on overpass-api.de. Every query carries an
explicit server-side [timeout]; results are cached for 24h and duplicate concurrent queries coalesce.
"""

from __future__ import annotations

import contextlib
import hashlib
from datetime import datetime
from typing import Any

from app.core.errors import ProviderError
from app.services.base import OSM_ATTRIBUTION, Fetched, ServiceDeps, make_provenance


async def run_query(
    deps: ServiceDeps, ql: str, *, pid: str, ttl: int, budget_s: float | None = None
) -> Fetched[dict[str, Any]]:
    s = deps.settings
    key = "overpass:" + hashlib.sha256(ql.encode()).hexdigest()

    async def fetch():
        return await deps.http.fetch_json(
            "overpass", s.overpass_mirrors, data={"data": ql}, timeout_s=s.overpass_timeout_s,
            retries=1, retry_timeouts=False, deadline_s=budget_s or s.overpass_budget_s,
        )

    try:
        (payload, used), hit = await deps.cache.get_or_fetch(key, ttl, fetch)
    except ProviderError as exc:
        return Fetched(
            None,
            make_provenance(pid, "OpenStreetMap via Overpass API", url=s.overpass_mirrors[0], kind="observed",
                            license="ODbL 1.0", attribution=OSM_ATTRIBUTION, status="failed", error=exc.message),
        )
    remark = (payload or {}).get("remark")
    status = "partial" if remark and "runtime error" in remark.lower() else "ok"
    prov = make_provenance(
        pid, "OpenStreetMap via Overpass API", url=used, kind="observed", license="ODbL 1.0",
        attribution=OSM_ATTRIBUTION, cache_hit=hit, status=status,
        limitations=["OSM coverage and tagging are volunteer-maintained and may be incomplete or outdated."],
        error=remark if status == "partial" else None,
    )
    ts = (payload or {}).get("osm3s", {}).get("timestamp_osm_base")
    if ts:
        with contextlib.suppress(ValueError):
            prov.issued_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return Fetched(payload, prov)

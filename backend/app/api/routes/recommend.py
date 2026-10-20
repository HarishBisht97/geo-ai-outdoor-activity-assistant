from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.api.state import AppServices, client_ip, services
from app.core.errors import AppError, OverloadedError, RateLimitedError
from app.core.logging import log_event, request_id_var
from app.schemas.requests import RecommendRequest
from app.schemas.responses import ErrorResponse, RecommendResponse

router = APIRouter(prefix="/api/v1", tags=["recommendations"])
logger = logging.getLogger(__name__)

ERROR_RESPONSES = {
    400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 429: {"model": ErrorResponse},
    503: {"model": ErrorResponse}, 504: {"model": ErrorResponse},
}


class GatewayTimeout(AppError):
    status_code = 504
    code = "timeout"


async def _admit(svc: AppServices, request: Request) -> None:
    ok, retry = svc.limiter.allow(client_ip(request))
    if not ok:
        raise RateLimitedError("Too many requests; please wait a minute.", {"retry_after_s": retry})
    try:
        await asyncio.wait_for(svc.semaphore.acquire(), timeout=10)
    except TimeoutError as exc:
        raise OverloadedError("The server is handling other requests; please retry shortly.") from exc


@router.post("/recommend", response_model=RecommendResponse, responses=ERROR_RESPONSES,
             summary="Recommend the best nearby place and time for an outdoor activity")
async def recommend(body: RecommendRequest, request: Request, svc: AppServices = Depends(services)) -> RecommendResponse:
    """Synchronous endpoint. Typical latency on the CPU deployment is 20-70 s (live data + SLM).
    Use `/api/v1/recommend/stream` to receive progress events and the ranking before the explanation."""
    await _admit(svc, request)
    try:
        resp = await asyncio.wait_for(svc.pipeline.run(body, request_id_var.get()), svc.settings.request_timeout_s)
    except TimeoutError as exc:
        raise GatewayTimeout("The request took too long. External data services may be slow; please retry.") from exc
    finally:
        svc.semaphore.release()
    svc.record_sources(resp.sources)
    return resp


@router.post("/recommend/stream", responses=ERROR_RESPONSES,
             summary="Same as /recommend, streamed as Server-Sent Events",
             description="Events: `stage` {stage, detail}; `ranking` (RecommendResponse without narrative); "
                         "`done` (full RecommendResponse); `error` {code, message}.")
async def recommend_stream(body: RecommendRequest, request: Request, svc: AppServices = Depends(services)):
    await _admit(svc, request)
    queue: asyncio.Queue = asyncio.Queue()
    rid = request_id_var.get()

    async def emit(event: str, data: dict) -> None:
        await queue.put((event, data))

    async def runner():
        request_id_var.set(rid)
        try:
            resp = await asyncio.wait_for(svc.pipeline.run(body, rid, emit), svc.settings.request_timeout_s)
            svc.record_sources(resp.sources)
            await queue.put(("done", resp.model_dump(mode="json")))
        except TimeoutError:
            await queue.put(("error", {"code": "timeout", "message": "The request took too long; please retry.",
                                       "request_id": rid}))
        except AppError as exc:
            await queue.put(("error", {"code": exc.code, "message": exc.message, "request_id": rid}))
        except Exception:  # noqa: BLE001
            log_event(logger, "stream_failed", logging.ERROR)
            logger.exception("pipeline error")
            await queue.put(("error", {"code": "internal_error", "message": "Unexpected server error.",
                                       "request_id": rid}))
        finally:
            svc.semaphore.release()
            await queue.put(None)

    task = asyncio.create_task(runner())

    async def events() -> AsyncIterator[dict]:
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                event, data = item
                yield {"event": event, "data": json.dumps(data)}
        finally:
            if not task.done():
                task.cancel()

    return EventSourceResponse(events(), ping=15, headers={"X-Request-ID": rid, "Cache-Control": "no-store",
                                                          "X-Accel-Buffering": "no"})

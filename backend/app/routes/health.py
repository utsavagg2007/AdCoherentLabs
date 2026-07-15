"""/healthz (liveness) · /readyz (DB+Redis) · /metrics (Prometheus, guarded)."""

from __future__ import annotations

import base64
import secrets

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from .. import db, redis_client
from ..config import settings
from ..errors import ApiError
from ..services import queue as queue_service
from .. import metrics

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}


@router.get("/readyz", include_in_schema=False)
async def readyz(response: Response):
    db_ok = await db.ping()
    redis_ok = await redis_client.ping()
    ready = db_ok  # Redis down = degraded per §9.4, not unready (credit gate is Postgres)
    response.status_code = 200 if ready else 503
    return {"ready": ready, "db": db_ok,
            "redis": "ok" if redis_ok else "degraded"}


@router.get("/metrics", include_in_schema=False)
async def metrics_endpoint(request: Request):
    if settings.metrics_basic_auth:
        auth = request.headers.get("Authorization", "")
        expected = "Basic " + base64.b64encode(
            settings.metrics_basic_auth.encode()).decode()
        if not secrets.compare_digest(auth, expected):
            raise ApiError(401, "unauthenticated", "Metrics require basic auth.",
                           headers={"WWW-Authenticate": "Basic"})
    try:
        stats = await queue_service.stats()
        metrics.set_queue_stats(stats)
    except Exception:
        pass  # a DB blip must not break the scrape
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

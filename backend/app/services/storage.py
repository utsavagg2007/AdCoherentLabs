"""Supabase Storage over Kong with the service role key (SERVER ONLY).

Objects live at assets/<org_id>/<submission_id>/<random>.<ext> (0005 policy
convention). The API never serves file bytes to clients — the frontend gets
short-lived signed URLs straight from Storage under RLS (§13.3).
"""

from __future__ import annotations

import httpx
import structlog

from ..config import settings
from ..errors import ApiError

logger = structlog.get_logger("app.storage")

BUCKET = "assets"


def _headers(content_type: str | None = None) -> dict:
    if not settings.supabase_service_role_key:
        raise ApiError(500, "internal", "Storage is not configured.")
    h = {"Authorization": f"Bearer {settings.supabase_service_role_key}",
         "apikey": settings.supabase_service_role_key}
    if content_type:
        h["Content-Type"] = content_type
    return h


async def put_object(path: str, data: bytes, content_type: str) -> None:
    url = f"{settings.supabase_url}/storage/v1/object/{BUCKET}/{path}"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, content=data,
                                 headers=_headers(content_type))
    if resp.status_code not in (200, 201):
        logger.error("storage.put_failed", path=path, status=resp.status_code,
                     body=resp.text[:300])
        raise ApiError(500, "internal", "Failed to store the uploaded asset.")


async def delete_object(path: str) -> bool:
    url = f"{settings.supabase_url}/storage/v1/object/{BUCKET}/{path}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.delete(url, headers=_headers())
        return resp.status_code == 200
    except httpx.HTTPError:
        logger.warning("storage.delete_failed", path=path)
        return False


def download_object_sync(path: str, timeout: int = 120) -> bytes:
    """Worker-side download (sync process)."""
    url = f"{settings.supabase_url}/storage/v1/object/{BUCKET}/{path}"
    resp = httpx.get(url, headers=_headers(), timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"storage download failed ({resp.status_code}) for {path}")
    return resp.content


def delete_object_sync(path: str) -> bool:
    """Scheduler-side deletion (retention job)."""
    url = f"{settings.supabase_url}/storage/v1/object/{BUCKET}/{path}"
    try:
        resp = httpx.delete(url, headers=_headers(), timeout=30)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False

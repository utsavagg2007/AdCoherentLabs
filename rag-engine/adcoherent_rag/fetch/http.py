"""Shared HTTP helpers: retries, backoff, UA, FetchResult construction."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import requests

from .. import config
from .base import FetchError

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def get(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = config.HTTP_TIMEOUT,
    retries: int = config.HTTP_RETRIES,
    source_id: str | None = None,
) -> requests.Response:
    """GET with retry/backoff. Raises FetchError on final failure."""
    merged = {"User-Agent": config.HTTP_USER_AGENT, **(headers or {})}
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(
                url,
                headers=merged,
                timeout=(config.HTTP_CONNECT_TIMEOUT, timeout),
                allow_redirects=True,
            )
            if resp.status_code in _RETRYABLE_STATUS and attempt < retries:
                time.sleep(config.HTTP_BACKOFF_SECONDS * (2**attempt))
                continue
            if resp.status_code >= 400:
                raise FetchError(
                    f"HTTP {resp.status_code} for {url}", source_id=source_id, url=url
                )
            return resp
        except FetchError:
            raise
        except requests.RequestException as e:
            last_err = e
            if attempt < retries:
                time.sleep(config.HTTP_BACKOFF_SECONDS * (2**attempt))
    raise FetchError(f"request failed for {url}: {last_err}", source_id=source_id, url=url)


def fetch_url(
    source_id: str,
    url: str,
    *,
    kind: str,
    extra_meta: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
):
    """GET a URL and wrap it in a FetchResult (meta['kind'] = kind)."""
    from ..models import FetchResult  # local import to avoid cycles

    resp = get(url, headers=headers, source_id=source_id)
    meta: dict[str, Any] = {"kind": kind}
    if extra_meta:
        meta.update(extra_meta)
    return FetchResult(
        source_id=source_id,
        requested_url=url,
        resolved_url=str(resp.url),
        content=resp.content,
        content_type=resp.headers.get("Content-Type", ""),
        http_status=resp.status_code,
        fetched_at=datetime.now(timezone.utc),
        meta=meta,
    )

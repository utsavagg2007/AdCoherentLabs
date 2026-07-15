"""Idempotency-Key support for POST /v1/submissions (§6.2).

The key→response mapping lives in Postgres for 24 h; a duplicate replays the
original response verbatim, and the same key with a DIFFERENT body is a 409
(a client bug worth surfacing loudly, not masking).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg

from .. import db
from ..errors import ApiError


def request_fingerprint(parts: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


async def lookup(org_id: str, endpoint: str, key: str,
                 fingerprint: str) -> dict | None:
    row = await db.fetch_one(
        "select request_hash, status_code, response from app.idempotency_keys "
        "where org_id = %s and endpoint = %s and key = %s and expires_at > now()",
        (org_id, endpoint, key))
    if row is None:
        return None
    if row["request_hash"] != fingerprint:
        raise ApiError(409, "conflict",
                       "Idempotency-Key was already used with a different request body.")
    return {"status_code": row["status_code"], "response": row["response"]}


async def store_tx(conn: psycopg.AsyncConnection, org_id: str, endpoint: str,
                   key: str, fingerprint: str, status_code: int,
                   response: dict) -> None:
    await conn.execute(
        "insert into app.idempotency_keys "
        "  (org_id, endpoint, key, request_hash, status_code, response) "
        "values (%s, %s, %s, %s, %s, %s::jsonb) "
        "on conflict (org_id, endpoint, key) do nothing",
        (org_id, endpoint, key, fingerprint, status_code, json.dumps(response)))

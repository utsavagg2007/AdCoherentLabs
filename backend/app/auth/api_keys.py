"""X-API-Key auth + issuance — the thin async wrapper over the engine/saas.py
contract (§5): ``ack_<hex>`` plaintext shown exactly once, sha256 at rest,
prefix-displayed, scoped, revocable, entitlement-gated, last_used_at stamped.
"""

from __future__ import annotations

import hashlib
import secrets

from .. import db
from ..errors import ApiError

VALID_SCOPES = ("submit", "read", "admin")
PREFIX_LEN = 12  # "ack_" + 8 hex chars — enough to identify, useless to guess


def mint() -> tuple[str, str, str]:
    """(plaintext, sha256_hash, display_prefix) — plaintext is never stored."""
    plaintext = "ack_" + secrets.token_hex(24)
    return plaintext, hashlib.sha256(plaintext.encode()).hexdigest(), plaintext[:PREFIX_LEN]


def hash_of(plaintext: str) -> str:
    return hashlib.sha256((plaintext or "").encode()).hexdigest()


async def verify(plaintext: str) -> dict:
    """Resolve a presented key or 401. Checks, in order: hash exists, not
    revoked, org still entitled to API access. Returns org_id, scopes,
    key_id, prefix-ish name, and the optional per-key rpm cap."""
    row = await db.fetch_one(
        "select k.id::text as key_id, k.org_id::text, k.name, k.scopes, "
        "       k.revoked_at, k.rate_limit_rpm, e.api_access "
        "from public.api_keys k "
        "join public.plan_entitlements e on e.tier = app.org_tier(k.org_id) "
        "where k.key_hash = %s", (hash_of(plaintext),))
    if row is None:
        raise ApiError(401, "unauthenticated", "Unknown API key.")
    if row["revoked_at"] is not None:
        raise ApiError(401, "unauthenticated", "API key is revoked.")
    if not row["api_access"]:
        raise ApiError(403, "forbidden",
                       "This org's tier no longer includes API access.")
    await db.execute(
        "update public.api_keys set last_used_at = now() where id = %s",
        (row["key_id"],))
    return row


def require_scope(scopes: list[str] | None, needed: str) -> None:
    if needed not in (scopes or []):
        raise ApiError(403, "forbidden", f"API key lacks the '{needed}' scope.")

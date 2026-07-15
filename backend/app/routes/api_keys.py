"""API key management (§11): admin+ with the api_access entitlement.
The secret is shown exactly once; only its sha256 is stored (engine contract)."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends

from .. import db
from ..auth import api_keys as keylib
from ..deps import AuthContext
from ..errors import ApiError, not_found
from ..ratelimit_deps import rate_limited
from ..schemas import ApiKeyCreate

router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])


@router.get("")
async def list_keys(ctx: AuthContext = Depends(rate_limited)):
    ctx.require_role("admin")
    rows = await db.fetch_all(
        "select id::text, name, scopes, rate_limit_rpm, created_by::text, "
        "       created_at, last_used_at, revoked_at "
        "from public.api_keys where org_id = %s order by created_at desc",
        (ctx.org_id,))
    return {"api_keys": rows}


@router.post("", status_code=201)
async def issue_key(body: ApiKeyCreate, ctx: AuthContext = Depends(rate_limited)):
    ctx.require_role("admin")
    ctx.require_entitlement("api_access")
    if ctx.principal != "user":
        raise ApiError(403, "forbidden", "Keys are issued from a user session.")
    ctx.require_step_up()          # minting credentials is a privileged action
    org_rpm = ctx.entitlements.get("api_rpm") or 0
    if body.rate_limit_rpm and org_rpm and body.rate_limit_rpm > org_rpm:
        raise ApiError(422, "validation_error",
                       f"Per-key cap must be <= the org cap ({org_rpm} rpm).")
    plaintext, key_hash, prefix = keylib.mint()
    async with db.transaction() as conn:
        cur = await conn.execute(
            "insert into public.api_keys "
            "  (org_id, name, key_hash, scopes, created_by, rate_limit_rpm) "
            "values (%s, %s, %s, %s, %s, %s) returning id::text",
            (ctx.org_id, body.name, key_hash, body.scopes, ctx.user_id,
             body.rate_limit_rpm))
        key_id = (await cur.fetchone())["id"]
        await conn.execute(
            "select app.log_audit_event(%s, %s, 'api_key.created', %s, %s::jsonb)",
            (ctx.org_id, ctx.user_id, f"api_key:{key_id}",
             json.dumps({"name": body.name, "scopes": body.scopes,
                         "rate_limit_rpm": body.rate_limit_rpm})))
    return {"api_key": plaintext,     # the ONLY time the secret ever appears
            "id": key_id, "prefix": prefix, "scopes": body.scopes,
            "note": "Store this secret now - it cannot be shown again."}


@router.delete("/{key_id}")
async def revoke_key(key_id: uuid.UUID, ctx: AuthContext = Depends(rate_limited)):
    ctx.require_role("admin")
    ctx.require_step_up()
    async with db.transaction() as conn:
        cur = await conn.execute(
            "update public.api_keys set revoked_at = now() "
            "where id = %s and org_id = %s and revoked_at is null "
            "returning id::text", (str(key_id), ctx.org_id))
        row = await cur.fetchone()
        if row is None:
            raise not_found()
        await conn.execute(
            "select app.log_audit_event(%s, %s, 'api_key.revoked', %s, '{}'::jsonb)",
            (ctx.org_id, ctx.user_id, f"api_key:{key_id}"))
    return {"revoked": str(key_id)}

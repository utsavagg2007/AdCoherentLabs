"""Org + membership management (§11). Org creation goes through
app.create_org() (atomic org + owner + free sub + first cycle grant) with the
caller's identity injected as request.jwt.claims so auth.uid() resolves —
one code path for PostgREST and this API."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends

from .. import db
from ..deps import AuthContext, auth_context, get_entitlements
from ..errors import ApiError, not_found
from ..ratelimit_deps import rate_limited
from ..schemas import MemberAdd, MemberPatch, OrgCreate
from ..services import credits

router = APIRouter(prefix="/v1/orgs", tags=["orgs"])


@router.post("", status_code=201)
async def create_org(body: OrgCreate, ctx: AuthContext = Depends(auth_context)):
    if ctx.principal != "user":
        raise ApiError(403, "forbidden", "Org creation requires a user session.")
    async with db.transaction() as conn:
        await conn.execute("select set_config('request.jwt.claims', %s, true)",
                           (json.dumps({"sub": ctx.user_id, "role": "authenticated"}),))
        cur = await conn.execute("select app.create_org(%s)::text as org_id",
                                 (body.name,))
        org_id = (await cur.fetchone())["org_id"]
        await conn.execute(
            "select app.log_audit_event(%s, %s, 'org.created', %s, %s::jsonb)",
            (org_id, ctx.user_id, f"org:{org_id}", json.dumps({"name": body.name})))
    return {"org_id": org_id, "name": body.name, "tier": "free"}


@router.get("/me")
async def current_org(ctx: AuthContext = Depends(rate_limited)):
    org = await db.fetch_one(
        "select id::text, name, created_at from public.orgs where id = %s",
        (ctx.org_id,))
    if org is None:
        raise not_found()
    return {"org": org, "role": ctx.role, "tier": ctx.tier,
            "entitlements": {k: ctx.entitlements.get(k) for k in (
                "llm_model", "max_output_tokens", "credits_per_month",
                "api_rpm", "api_burst", "user_rpm", "max_concurrent_runs",
                "max_upload_mb", "submissions_per_day", "credit_packs_allowed",
                "api_access", "seats", "sso", "sla")},
            "credits": await credits.balance(ctx.org_id),
            "memberships": ctx.memberships}


@router.get("/members")
async def list_members(ctx: AuthContext = Depends(rate_limited)):
    ctx.require_scope("read")
    rows = await db.fetch_all(
        "select m.user_id::text, m.role, m.created_at, u.email "
        "from public.memberships m join auth.users u on u.id = m.user_id "
        "where m.org_id = %s order by m.created_at", (ctx.org_id,))
    return {"members": rows, "seats": ctx.entitlements.get("seats")}


@router.post("/members", status_code=201)
async def add_member(body: MemberAdd, ctx: AuthContext = Depends(rate_limited)):
    ctx.require_role("admin")
    ctx.require_step_up()          # tenant-membership change (audit spec)
    seats = ctx.entitlements.get("seats")
    if seats is not None:
        row = await db.fetch_one(
            "select count(*) as n from public.memberships where org_id = %s",
            (ctx.org_id,))
        if row["n"] >= seats:
            raise ApiError(403, "forbidden",
                           f"The '{ctx.tier}' plan is capped at {seats} seat(s).",
                           {"seats": seats})
    user = await db.fetch_one(
        "select id::text from auth.users where lower(email) = lower(%s)",
        (body.email,))
    if user is None:
        # v1 adds existing accounts; email-invite flow is a frontend phase.
        raise ApiError(404, "not_found",
                       "No account with that email exists yet - ask them to sign up first.")
    async with db.transaction() as conn:
        await conn.execute(
            "insert into public.memberships (org_id, user_id, role) "
            "values (%s, %s, %s) on conflict (org_id, user_id) do nothing",
            (ctx.org_id, user["id"], body.role))
        await conn.execute(
            "select app.log_audit_event(%s, %s, 'member.added', %s, %s::jsonb)",
            (ctx.org_id, ctx.user_id, f"user:{user['id']}",
             json.dumps({"role": body.role})))
    return {"user_id": user["id"], "role": body.role}


@router.patch("/members")
async def change_role(body: MemberPatch, ctx: AuthContext = Depends(rate_limited)):
    ctx.require_role("admin")
    ctx.require_step_up()
    target = await db.fetch_one(
        "select role from public.memberships where org_id = %s and user_id = %s",
        (ctx.org_id, body.user_id))
    if target is None:
        raise not_found()
    if target["role"] == "owner":
        raise ApiError(403, "forbidden", "The owner role cannot be reassigned here.")
    async with db.transaction() as conn:
        await conn.execute(
            "update public.memberships set role = %s "
            "where org_id = %s and user_id = %s",
            (body.role, ctx.org_id, body.user_id))
        await conn.execute(
            "select app.log_audit_event(%s, %s, 'member.role_changed', %s, %s::jsonb)",
            (ctx.org_id, ctx.user_id, f"user:{body.user_id}",
             json.dumps({"from": target["role"], "to": body.role})))
    return {"user_id": body.user_id, "role": body.role}


@router.delete("/members/{user_id}")
async def remove_member(user_id: str, ctx: AuthContext = Depends(rate_limited)):
    ctx.require_role("admin")
    ctx.require_step_up()
    target = await db.fetch_one(
        "select role from public.memberships where org_id = %s and user_id = %s",
        (ctx.org_id, user_id))
    if target is None:
        raise not_found()
    if target["role"] == "owner":
        raise ApiError(403, "forbidden", "The org owner cannot be removed.")
    async with db.transaction() as conn:
        await conn.execute(
            "delete from public.memberships where org_id = %s and user_id = %s",
            (ctx.org_id, user_id))
        await conn.execute(
            "select app.log_audit_event(%s, %s, 'member.removed', %s, '{}'::jsonb)",
            (ctx.org_id, ctx.user_id, f"user:{user_id}"))
    return {"removed": user_id}

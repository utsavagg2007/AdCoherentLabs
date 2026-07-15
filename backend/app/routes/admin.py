"""/v1/admin — internal staff only (ADMIN_EMAILS allowlist), every action
dual-logged: the org's audit trail AND a staff-attributed meta (§11)."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends

from .. import db
from ..deps import AuthContext
from ..errors import ApiError, not_found
from ..ratelimit_deps import rate_limited
from ..schemas import AdminCreditAdjust
from ..services import queue

router = APIRouter(prefix="/v1/admin", tags=["admin"])


async def staff_only(ctx: AuthContext = Depends(rate_limited)) -> AuthContext:
    if ctx.principal != "user" or not ctx.is_staff:
        # Do not advertise that the route exists.
        raise not_found()
    return ctx


@router.get("/queue")
async def queue_overview(ctx: AuthContext = Depends(staff_only)):
    return {"stats": await queue.stats(), "dlq": await queue.dlq_list()}


@router.post("/dlq/{job_id}/requeue")
async def requeue_dlq(job_id: int, ctx: AuthContext = Depends(staff_only)):
    job = await db.fetch_one(
        "select org_id::text, run_id::text from app.job_queue "
        "where id = %s and status = 'dlq'", (job_id,))
    if job is None:
        raise not_found()
    ok = await queue.dlq_requeue(job_id)
    if not ok:
        raise ApiError(409, "conflict", "Job is no longer in the DLQ.")
    await db.execute(
        "select app.log_audit_event(%s, %s, 'admin.dlq_requeued', %s, %s::jsonb)",
        (job["org_id"], ctx.user_id, f"job:{job_id}",
         json.dumps({"staff": ctx.email, "run_id": job["run_id"],
                     "note": "credits were refunded at DLQ; re-run is free"})))
    return {"requeued": job_id, "run_id": job["run_id"]}


@router.get("/orgs/{org_id}")
async def org_lookup(org_id: uuid.UUID, ctx: AuthContext = Depends(staff_only)):
    org = await db.fetch_one(
        "select o.id::text, o.name, o.created_at, s.tier, s.status, "
        "       s.grace_until, s.current_period_start, s.current_period_end "
        "from public.orgs o "
        "left join public.subscriptions s on s.org_id = o.id where o.id = %s",
        (str(org_id),))
    if org is None:
        raise not_found()
    bal = await db.fetch_one("select app.credit_balance(%s) as b", (str(org_id),))
    return {"org": org, "credits": bal["b"]}


@router.post("/orgs/{org_id}/credits")
async def adjust_credits(org_id: uuid.UUID, body: AdminCreditAdjust,
                         ctx: AuthContext = Depends(staff_only)):
    ctx.require_step_up()          # staff moving money: MFA-challenged session
    row = await db.fetch_one(
        "select app.adjust_credits_manual(%s, %s, %s, %s, %s) as r",
        (str(org_id), body.delta, body.bucket, ctx.user_id,
         f"[staff:{ctx.email}] {body.note}"))
    await db.execute(
        "select app.log_audit_event(%s, %s, 'admin.credits_adjusted', %s, %s::jsonb)",
        (str(org_id), ctx.user_id, f"org:{org_id}",
         json.dumps({"staff": ctx.email, "delta": body.delta,
                     "bucket": body.bucket, "note": body.note})))
    return row["r"]

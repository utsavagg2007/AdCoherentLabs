"""Findings: list per run/submission; reviewer+ approve | flag | dismiss
(audited). Inserts are engine-only (worker) — no create route exists."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends

from .. import db
from ..deps import AuthContext
from ..errors import not_found
from ..ratelimit_deps import rate_limited, rate_limited_reviewer
from ..schemas import FindingPatch

router = APIRouter(prefix="/v1/findings", tags=["findings"])

_COLS = ("id::text, run_id::text, framework, rule_ref, severity, verdict, "
         "location, message, remediation, status, reviewed_by::text, created_at")


@router.get("")
async def list_findings(ctx: AuthContext = Depends(rate_limited),
                        run_id: uuid.UUID | None = None,
                        submission_id: uuid.UUID | None = None,
                        status: str | None = None, limit: int = 100):
    ctx.require_scope("read")
    rows = await db.fetch_all(
        f"select {_COLS} from public.findings f where f.org_id = %s "
        "and (%s::uuid is null or f.run_id = %s) "
        "and (%s::uuid is null or f.run_id in "
        "     (select id from public.analysis_runs "
        "      where submission_id = %s and org_id = %s)) "
        "and (%s::text is null or f.status = %s) "
        "order by f.created_at desc limit %s",
        (ctx.org_id,
         str(run_id) if run_id else None, str(run_id) if run_id else None,
         str(submission_id) if submission_id else None,
         str(submission_id) if submission_id else None, ctx.org_id,
         status, status, min(max(limit, 1), 500)))
    return {"findings": rows}


@router.get("/{finding_id}")
async def get_finding(finding_id: uuid.UUID,
                      ctx: AuthContext = Depends(rate_limited)):
    ctx.require_scope("read")
    row = await db.fetch_one(
        f"select {_COLS} from public.findings f "
        "where f.id = %s and f.org_id = %s", (str(finding_id), ctx.org_id))
    if row is None:
        raise not_found()
    return {"finding": row}


@router.patch("/{finding_id}")
async def review_finding(finding_id: uuid.UUID, body: FindingPatch,
                         ctx: AuthContext = Depends(rate_limited_reviewer)):
    ctx.require_scope("submit")
    async with db.transaction() as conn:
        cur = await conn.execute(
            "update public.findings set status = %s, reviewed_by = %s "
            "where id = %s and org_id = %s returning id::text, status",
            (body.status, ctx.user_id, str(finding_id), ctx.org_id))
        row = await cur.fetchone()
        if row is None:
            raise not_found()
        await conn.execute(
            "select app.log_audit_event(%s, %s, %s, %s, %s::jsonb)",
            (ctx.org_id, ctx.user_id, f"finding.{body.status}",
             f"finding:{finding_id}", json.dumps({"via": ctx.principal})))
    return {"finding": row}

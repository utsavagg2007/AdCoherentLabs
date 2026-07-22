"""Run status, reports, and the operator-resume path (§11).

The report is the engine's persisted document: the worker stores the full
EngineRunResult as the 'report' layer output; older sync-path runs fall back
to an assembly from the llm/rule layer outputs. Reports remain decision
support, not legal advice — the disclaimer rides on every response (§14.2).
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends

from .. import db
from ..deps import AuthContext
from ..errors import ApiError, not_found
from ..ratelimit_deps import rate_limited, rate_limited_reviewer
from ..schemas import ResumeRequest
from ..services import queue

DISCLAIMER = ("AdCoherent reports are decision support for your compliance "
              "process, not legal advice.")

router = APIRouter(prefix="/v1/runs", tags=["runs"])


async def _own_run(run_id: str, org_id: str) -> dict:
    row = await db.fetch_one(
        "select id::text, submission_id::text, status, tier, model_id, "
        "       prompt_version, rulepack_version, rag_corpus_hash, "
        "       input_tokens, output_tokens, engine_run_id, "
        "       resumed_from_run_id::text, error, created_at, started_at, "
        "       finished_at "
        "from public.analysis_runs where id = %s and org_id = %s",
        (run_id, org_id))
    if row is None:
        raise not_found()   # cross-org ids are indistinguishable from absent
    return row


@router.get("")
async def list_runs(ctx: AuthContext = Depends(rate_limited),
                    status: str | None = None, limit: int = 50,
                    before: str | None = None):
    ctx.require_scope("read")
    rows = await db.fetch_all(
        "select id::text, submission_id::text, status, tier, model_id, "
        "       engine_run_id, created_at, started_at, finished_at "
        "from public.analysis_runs where org_id = %s "
        "and (%s::text is null or status = %s) "
        "and (%s::timestamptz is null or created_at < %s::timestamptz) "
        "order by created_at desc limit %s",
        (ctx.org_id, status, status, before, before, min(max(limit, 1), 200)))
    return {"runs": rows,
            "next_before": str(rows[-1]["created_at"]) if rows else None}


@router.get("/{run_id}")
async def get_run(run_id: uuid.UUID, ctx: AuthContext = Depends(rate_limited)):
    ctx.require_scope("read")
    run = await _own_run(str(run_id), ctx.org_id)
    job = await db.fetch_one(
        "select status as job_status, attempts, not_before, last_error "
        "from app.job_queue where run_id = %s", (str(run_id),))
    return {"run": run, "queue": job, "disclaimer": DISCLAIMER}


@router.get("/{run_id}/events")
async def get_run_events(run_id: uuid.UUID,
                         ctx: AuthContext = Depends(rate_limited),
                         after_id: int = 0, limit: int = 200):
    """The sanitized live-activity feed (0011): what the engine is doing
    right now, as fixed message templates + aggregate counts. Poll with
    after_id = the last id you have; run_status rides along so a client
    can stop polling on a terminal state."""
    ctx.require_scope("read")
    run = await _own_run(str(run_id), ctx.org_id)
    rows = await db.fetch_all(
        "select id, stage, event, message, detail, created_at "
        "from public.run_events "
        "where run_id = %s and org_id = %s and id > %s "
        "order by id asc limit %s",
        (str(run_id), ctx.org_id, after_id, min(max(limit, 1), 500)))
    return {"events": rows, "run_status": run["status"],
            "last_id": rows[-1]["id"] if rows else after_id}


@router.get("/{run_id}/report")
async def get_report(run_id: uuid.UUID, ctx: AuthContext = Depends(rate_limited)):
    ctx.require_scope("read")
    run = await _own_run(str(run_id), ctx.org_id)
    if run["status"] in ("queued", "running_cv", "running_nlp", "running_llm",
                         "running_rules", "reconciling"):
        raise ApiError(409, "conflict", "The run has not finished yet.",
                       {"status": run["status"]})
    report = await db.fetch_one(
        "select payload from public.layer_outputs "
        "where run_id = %s and org_id = %s and layer = 'report'",
        (str(run_id), ctx.org_id))
    if report:
        return {"report": report["payload"], "disclaimer": DISCLAIMER}
    # Sync-path runs (CLI/engine.saas) predate the 'report' layer: assemble.
    layers = {r["layer"]: r["payload"] for r in await db.fetch_all(
        "select layer, payload from public.layer_outputs "
        "where run_id = %s and org_id = %s", (str(run_id), ctx.org_id))}
    if not layers:
        raise not_found()
    llm, rule = layers.get("llm", {}), layers.get("rule", {})
    return {"report": {
        "run_id": run["engine_run_id"], "tier": run["tier"],
        "status": rule.get("engine_status"),
        "llm_review": llm.get("llm_review"),
        "rounds": llm.get("rounds"),
        "llm_rounds_used": llm.get("llm_rounds_used"),
        "max_llm_rounds": llm.get("max_llm_rounds"),
        "verification": rule.get("verification"),
        "human_review": rule.get("human_review"),
        "warnings": rule.get("warnings"),
        "provenance": {
            "model": run["model_id"], "prompt_version": run["prompt_version"],
            "ruleset_version": run["rulepack_version"],
            "rag_corpus_hash": run["rag_corpus_hash"],
            "saas": {"org_id": ctx.org_id, "analysis_run_id": run["id"],
                     "submission_id": run["submission_id"]}},
    }, "disclaimer": DISCLAIMER}


@router.post("/{run_id}/resume", status_code=202)
async def resume_run(run_id: uuid.UUID, body: ResumeRequest,
                     ctx: AuthContext = Depends(rate_limited_reviewer)):
    """Operator guidance for a human_review run: a NEW linked run, 0 credits
    (same creative — the existing quota contract), tokens still metered."""
    ctx.require_scope("submit")
    prev = await _own_run(str(run_id), ctx.org_id)
    if prev["status"] != "human_review":
        raise ApiError(409, "conflict",
                       "Only runs awaiting human review can be resumed.",
                       {"status": prev["status"]})
    new_run = str(uuid.uuid4())
    async with db.transaction() as conn:
        await conn.execute(
            "insert into public.analysis_runs "
            "  (id, submission_id, org_id, status, tier, model_id, "
            "   resumed_from_run_id, operator_guidance) "
            "values (%s, %s, %s, 'queued', %s, %s, %s, %s)",
            (new_run, prev["submission_id"], ctx.org_id, ctx.tier,
             ctx.entitlements.get("llm_model"), str(run_id), body.guidance))
        await queue.enqueue_tx(conn, new_run)
        await conn.execute(
            "select app.log_audit_event(%s, %s, 'run.resume_requested', %s, %s::jsonb)",
            (ctx.org_id, ctx.user_id, f"analysis_run:{new_run}",
             json.dumps({"resumed_from": str(run_id),
                         "guidance_chars": len(body.guidance),
                         "credits_charged": 0, "via": ctx.principal})))
    return {"run_id": new_run, "resumed_from_run_id": str(run_id),
            "credits_charged": 0}

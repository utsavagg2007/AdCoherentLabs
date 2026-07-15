"""POST /v1/submissions — the request that spends money (§6.2 steps 1–3).

Multipart (image / carousel / txt / html file) or JSON (inline text/html).
Pipeline: auth+role+billing+rate gates (dependency) → upload security
pipeline → ONE TRANSACTION: cycle grant → cost → submission/assets/run rows →
app.consume_credits (row-locked) → app.enqueue_run → COMMIT → 202.

Charge and enqueue commit together or not at all (D3). A 402 still records
and audits the rejected run (existing quota contract). The engine NEVER runs
in this process (Appendix C) — the API's job ends at COMMIT.
"""

from __future__ import annotations

import json
import uuid

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .. import db, metrics
from ..deps import AuthContext
from ..errors import ApiError, error_response, not_found
from ..ratelimit_deps import rate_limited, submit_gate
from ..schemas import InlineSubmission
from ..services import credits, idempotency, queue, storage, uploads

logger = structlog.get_logger("app.submissions")

router = APIRouter(prefix="/v1/submissions", tags=["submissions"])

_MAX_CARDS = 10


async def _parse_input(request: Request, ctx: AuthContext) -> tuple[list[uploads.ProcessedUpload], str, int, str | None, list[str]]:
    """→ (processed uploads, pricing_kind, cards, title, jurisdictions)."""
    content_type = (request.headers.get("content-type") or "").lower()
    max_mb = int(ctx.entitlements.get("max_upload_mb") or 10)

    if content_type.startswith("application/json"):
        body = InlineSubmission.model_validate(await request.json())
        try:
            processed = await uploads.process_inline(body.kind, body.content)
        except ApiError as exc:
            metrics.UPLOAD_REJECTS.labels(reason=exc.code).inc()
            raise
        return [processed], body.kind, 1, body.title, body.target_jurisdictions

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        files = [v for k, v in form.multi_items() if k in ("file", "files")]
        if not files:
            raise ApiError(422, "bad_asset", "Attach at least one file field named 'file'.")
        if len(files) > _MAX_CARDS:
            raise ApiError(422, "bad_asset", f"Carousels are capped at {_MAX_CARDS} cards.")
        title = str(form.get("title") or "") or None
        juris_raw = str(form.get("target_jurisdictions") or "")
        jurisdictions = [j.strip() for j in juris_raw.split(",") if j.strip()]
        processed = []
        for f in files:
            data = await f.read()
            try:
                processed.append(await uploads.process_file(data, f.filename or "", max_mb))
            except ApiError as exc:
                metrics.UPLOAD_REJECTS.labels(reason=exc.code).inc()
                raise
        kinds = {p.kind for p in processed}
        if len(kinds) > 1:
            raise ApiError(422, "bad_asset",
                           "Mixed asset kinds in one submission are not supported.")
        kind = kinds.pop()
        if kind != "image" and len(processed) > 1:
            raise ApiError(422, "bad_asset", "Only image carousels may have multiple files.")
        pricing_kind = "carousel" if (kind == "image" and len(processed) > 1) else kind
        return processed, pricing_kind, len(processed), title, jurisdictions

    raise ApiError(415, "unsupported_media_type",
                   "Send multipart/form-data or application/json.")


@router.post("", status_code=202)
async def create_submission(request: Request,
                            ctx: AuthContext = Depends(submit_gate)):
    processed, pricing_kind, cards, title, jurisdictions = await _parse_input(request, ctx)

    idem_key = request.headers.get("Idempotency-Key")
    fingerprint = idempotency.request_fingerprint({
        "org": ctx.org_id, "kind": pricing_kind, "title": title,
        "jurisdictions": jurisdictions,
        "checksums": [p.checksum for p in processed]})
    if idem_key:
        replay = await idempotency.lookup(ctx.org_id, "submissions", idem_key, fingerprint)
        if replay:
            return JSONResponse(status_code=replay["status_code"],
                                content=replay["response"])

    submission_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    # Storage before the transaction (paths need ids); rolled back best-effort
    # if the transaction fails.
    stored_paths: list[tuple[uploads.ProcessedUpload, str]] = []
    for p in processed:
        path = uploads.storage_key(ctx.org_id, submission_id, p.extension)
        await storage.put_object(path, p.data, p.content_type)
        stored_paths.append((p, path))

    actor = ctx.user_id  # None for API keys — audit meta carries the key id
    try:
        async with db.transaction() as conn:
            await credits.ensure_cycle_grant_tx(conn, ctx.org_id)
            cost = await credits.cost_tx(conn, ctx.org_id, pricing_kind, cards)

            await conn.execute(
                "insert into public.submissions "
                "  (id, org_id, created_by, title, target_jurisdictions, params) "
                "values (%s, %s, %s, %s, %s, %s::jsonb)",
                (submission_id, ctx.org_id,
                 actor or await _service_actor(conn, ctx), title,
                 jurisdictions or None,
                 json.dumps({"pricing_kind": pricing_kind, "cards": cards,
                             "via": ctx.principal})))
            for p, path in stored_paths:
                await conn.execute(
                    "insert into public.assets (submission_id, org_id, kind, "
                    "  storage_path, checksum, scan_status) "
                    "values (%s, %s, %s, %s, %s, 'clean')",
                    (submission_id, ctx.org_id, p.kind, path, p.checksum))
            await conn.execute(
                "insert into public.analysis_runs "
                "  (id, submission_id, org_id, status, tier, model_id) "
                "values (%s, %s, %s, 'queued', %s, %s)",
                (run_id, submission_id, ctx.org_id, ctx.tier,
                 ctx.entitlements.get("llm_model")))

            decision = await credits.consume_tx(conn, ctx.org_id, run_id, cost)

            if not decision.get("allowed"):
                # Record + audit the rejected attempt, then commit THAT (the
                # existing run.quota_rejected contract) and answer 402.
                await conn.execute(
                    "update public.analysis_runs set status = 'failed', "
                    "  finished_at = now(), error = %s where id = %s",
                    (f"rejected: insufficient credits (needed "
                     f"{decision.get('needed')}, balance {decision.get('balance')})",
                     run_id))
                await conn.execute(
                    "select app.log_audit_event(%s, %s, 'run.quota_rejected', %s, %s::jsonb)",
                    (ctx.org_id, actor, f"analysis_run:{run_id}",
                     json.dumps({"needed": decision.get("needed"),
                                 "balance": decision.get("balance"),
                                 "tier": ctx.tier, "via": ctx.principal})))
                body = {"error": {"code": "insufficient_credits",
                                  "message": f"Run costs {decision.get('needed')} credits; "
                                             f"balance is {decision.get('balance')}.",
                                  "request_id": request.state.request_id,
                                  "details": {"needed": decision.get("needed"),
                                              "balance": decision.get("balance"),
                                              "packs_url": "/v1/credits/checkout"}}}
                if idem_key:
                    await idempotency.store_tx(conn, ctx.org_id, "submissions",
                                               idem_key, fingerprint, 402, body)
                return JSONResponse(status_code=402, content=body)

            job_id = await queue.enqueue_tx(conn, run_id)
            response_body = {
                "submission_id": submission_id, "run_id": run_id,
                "credits_charged": decision["charged"],
                "balance": {"subscription_credits": decision["sub_bal"],
                            "purchased_credits": decision["pack_bal"]}}
            await conn.execute(
                "select app.log_audit_event(%s, %s, 'submission.created', %s, %s::jsonb)",
                (ctx.org_id, actor, f"submission:{submission_id}",
                 json.dumps({"kind": pricing_kind, "cards": cards, "title": title,
                             "credits_charged": decision["charged"],
                             "job_id": job_id, "via": ctx.principal,
                             "api_key_id": ctx.api_key_id})))
            if idem_key:
                await idempotency.store_tx(conn, ctx.org_id, "submissions",
                                           idem_key, fingerprint, 202, response_body)
    except ApiError:
        await _cleanup_storage(stored_paths)
        raise
    except Exception:
        await _cleanup_storage(stored_paths)
        logger.exception("submission.tx_failed", submission_id=submission_id)
        raise ApiError(500, "internal", "Submission could not be recorded.")

    metrics.CREDITS_CHARGED.labels(tier=ctx.tier).inc(decision["charged"])
    return JSONResponse(status_code=202, content=response_body)


async def _service_actor(conn, ctx: AuthContext) -> str:
    """submissions.created_by is NOT NULL → for API-key submissions attribute
    to the key's creator (the accountable human who minted the key)."""
    cur = await conn.execute(
        "select created_by::text as u from public.api_keys where id = %s",
        (ctx.api_key_id,))
    row = await cur.fetchone()
    if row is None:
        raise ApiError(401, "unauthenticated", "API key no longer exists.")
    return row["u"]


async def _cleanup_storage(stored: list) -> None:
    for _, path in stored:
        await storage.delete_object(path)


# -- reads ----------------------------------------------------------------------

@router.get("")
async def list_submissions(ctx: AuthContext = Depends(rate_limited),
                           limit: int = 50, before: str | None = None):
    ctx.require_scope("read")
    rows = await db.fetch_all(
        "select id::text, title, created_by::text, target_jurisdictions, "
        "       created_at "
        "from public.submissions where org_id = %s "
        "and (%s::timestamptz is null or created_at < %s::timestamptz) "
        "order by created_at desc limit %s",
        (ctx.org_id, before, before, min(max(limit, 1), 200)))
    return {"submissions": rows,
            "next_before": str(rows[-1]["created_at"]) if rows else None}


@router.get("/{submission_id}")
async def get_submission(submission_id: uuid.UUID,
                         ctx: AuthContext = Depends(rate_limited)):
    ctx.require_scope("read")
    sub = await db.fetch_one(
        "select id::text, title, created_by::text, target_jurisdictions, "
        "       params, created_at "
        "from public.submissions where id = %s and org_id = %s",
        (str(submission_id), ctx.org_id))
    if sub is None:
        raise not_found()
    assets = await db.fetch_all(
        "select id::text, kind, storage_path, checksum, scan_status, created_at "
        "from public.assets where submission_id = %s and org_id = %s "
        "order by created_at", (str(submission_id), ctx.org_id))
    runs = await db.fetch_all(
        "select id::text, status, tier, model_id, engine_run_id, "
        "       resumed_from_run_id::text, created_at, started_at, finished_at "
        "from public.analysis_runs where submission_id = %s and org_id = %s "
        "order by created_at", (str(submission_id), ctx.org_id))
    return {"submission": sub, "assets": assets, "runs": runs}

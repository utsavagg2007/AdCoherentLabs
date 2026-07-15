"""Executes one leased job against the engine.saas data plane (§6.2 step 5).

Reuses the engine's own persistence verbatim — SupabaseDataPlane methods,
_apply_framework_entitlements, _persist_outcome — against the run row the API
pre-created. Nothing here charges credits (Appendix C: the charge happened at
enqueue); a DLQ'd job refunds them (§10.3).

The tier is fetched from the DB via app.org_tier at execution time — never
from the job payload — so a plan change between submit and execution takes
effect on this very run.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

import structlog

from engine.orchestrator import (DEFAULT_MAX_LLM_ROUNDS, prepare_asset,
                                 resume_with_human_guidance, review_and_verify)
from engine.saas import (SupabaseDataPlane, _apply_framework_entitlements,
                         _persist_outcome)

from app.services import storage
from . import providers

logger = structlog.get_logger("worker.executor")


class RunAttemptFailed(Exception):
    """One attempt failed; the queue's taxonomy (§10.3) decides what's next."""

    def __init__(self, message: str, provider: str | None = None):
        super().__init__(message)
        self.provider = provider


@dataclass
class JobOutcome:
    engine_status: str          # passed | human_review
    findings: int | None = None


def _load_run(db: SupabaseDataPlane, run_id: str) -> dict:
    row = db._one(
        "select r.id::text, r.submission_id::text, r.org_id::text, r.status, "
        "       r.resumed_from_run_id::text, r.operator_guidance, "
        "       s.created_by::text, s.title, s.target_jurisdictions, s.params "
        "from public.analysis_runs r "
        "join public.submissions s on s.id = r.submission_id "
        "where r.id = %s", (run_id,))
    if row is None:
        raise RunAttemptFailed(f"analysis_runs row {run_id} vanished")
    return row


def _load_input(db: SupabaseDataPlane, run: dict, tmpdir: str) -> dict:
    """Rebuild the engine input from assets rows + storage objects."""
    assets = db._all(
        "select kind, storage_path from public.assets "
        "where submission_id = %s and org_id = %s order by created_at",
        (run["submission_id"], run["org_id"]))
    if not assets:
        raise RunAttemptFailed("submission has no assets")
    kinds = {a["kind"] for a in assets}
    if any(a["storage_path"] is None for a in assets):
        raise RunAttemptFailed("asset object no longer exists (retention purge?)")
    if kinds == {"text"} or kinds == {"html"}:
        raw = storage.download_object_sync(assets[0]["storage_path"])
        text = raw.decode("utf-8", errors="replace")
        return {"text": text} if kinds == {"text"} else {"html": text}
    if kinds == {"image"}:
        paths: list[str] = []
        for i, a in enumerate(assets):
            ext = Path(a["storage_path"]).suffix or ".png"
            p = Path(tmpdir) / f"card_{i}{ext}"
            p.write_bytes(storage.download_object_sync(a["storage_path"]))
            paths.append(str(p))
        return {"image_path": paths if len(paths) > 1 else paths[0]}
    raise RunAttemptFailed(f"unsupported asset kinds {sorted(kinds)}")


def _clear_stale_outputs(db: SupabaseDataPlane, run_id: str, org_id: str) -> None:
    """A retried attempt must not duplicate findings (idempotency rule §6.2);
    layer_outputs upsert by (run, layer) already."""
    db._exec("delete from public.findings where run_id = %s and org_id = %s",
             (run_id, org_id))


def execute_job(db: SupabaseDataPlane, job: dict) -> JobOutcome:
    """Runs the engine for job['run_id']. Raises RunAttemptFailed for the
    §10.3 taxonomy; returns on complete/human_review."""
    run_id, org_id = job["run_id"], job["org_id"]
    run = _load_run(db, run_id)
    ent = db.get_entitlements(org_id)          # the DB decides, per run
    provider = ent.llm_provider

    if providers.breaker_is_open(provider):
        raise BreakerOpen(provider)
    if not providers.acquire_slot(provider):
        raise NoProviderSlot(provider)

    try:
        _clear_stale_outputs(db, run_id, org_id)
        with tempfile.TemporaryDirectory(prefix=f"run-{run_id[:8]}-") as tmpdir:
            if run["resumed_from_run_id"] and run["operator_guidance"]:
                result = _execute_resume(db, run, ent)
            else:
                result = _execute_fresh(db, run, ent, tmpdir)

        if result.status == "llm_error":
            providers.record_failure(provider)
            raise RunAttemptFailed(
                f"llm_error: {result.llm_error or 'unknown provider failure'}",
                provider=provider)

        providers.record_success(provider)
        dump = result.model_dump(mode="json")
        _persist_outcome(db, run_id=run_id, org_id=org_id,
                         user_id=run["created_by"], ent=ent, result=result)
        db.save_layer_output(run_id, org_id, "report", dump)
        return JobOutcome(engine_status=result.status)
    finally:
        providers.release_slot(provider)


def _execute_fresh(db: SupabaseDataPlane, run: dict, ent, tmpdir: str):
    run_id, org_id = run["id"], run["org_id"]
    engine_input = _load_input(db, run, tmpdir)

    db.set_run(run_id, status="running_cv", started=True)
    db.audit(org_id, run["created_by"], "run.started", f"analysis_run:{run_id}",
             {"tier": ent.tier, "model": ent.llm_model, "async": True})
    asset = prepare_asset(product_tier=ent.tier,
                          target_jurisdictions=run["target_jurisdictions"],
                          **engine_input)
    db.set_run(run_id, status="running_nlp")
    dropped = _apply_framework_entitlements(asset, ent)
    bypassed = dropped[:1] == ["__bypass__"]
    db.save_layer_output(run_id, org_id, "cv", {
        "provenance": asset.get("provenance", {}),
        "segments": len(asset.get("segments", []))})
    db.save_layer_output(run_id, org_id, "nlp", asset)

    db.set_run(run_id, status="running_llm")
    result = review_and_verify(asset, ent.tier,
                               max_llm_rounds=DEFAULT_MAX_LLM_ROUNDS)

    if bypassed:
        result.warnings.append(
            "framework entitlement filter would have removed EVERY routed "
            f"framework ({dropped[1:]}) - routing kept as-is; review this "
            f"org's plan ({ent.tier})")
    elif dropped:
        result.warnings.append(
            f"frameworks outside the {ent.tier} plan were not reviewed: "
            + ", ".join(dropped))
    result.provenance["saas"] = {
        "org_id": org_id, "submission_id": run["submission_id"],
        "analysis_run_id": run_id, "tier_source": "supabase:app.org_tier",
        "frameworks_dropped_by_plan": [] if bypassed else dropped,
        "executed_by": "worker"}
    return result


def _execute_resume(db: SupabaseDataPlane, run: dict, ent):
    """Operator-guided single round over the stored Layer-1/2 output — no
    re-OCR, no credit charge, tokens still metered (§8.1)."""
    run_id, org_id = run["id"], run["org_id"]
    asset = db.load_asset_representation(run["resumed_from_run_id"])
    db.set_run(run_id, status="running_llm", started=True)
    db.audit(org_id, run["created_by"], "run.resumed", f"analysis_run:{run_id}",
             {"resumed_from": run["resumed_from_run_id"], "tier": ent.tier,
              "guidance_chars": len(run["operator_guidance"]), "async": True})
    result = resume_with_human_guidance(
        asset, run["operator_guidance"], product_tier=ent.tier)
    db.save_layer_output(run_id, org_id, "nlp", asset)
    result.provenance["saas"] = {
        "org_id": org_id, "submission_id": run["submission_id"],
        "analysis_run_id": run_id,
        "resumed_from_run_id": run["resumed_from_run_id"],
        "tier_source": "supabase:app.org_tier", "executed_by": "worker"}
    return result


class BreakerOpen(Exception):
    def __init__(self, provider: str):
        super().__init__(f"circuit breaker open for {provider}")
        self.provider = provider


class NoProviderSlot(Exception):
    def __init__(self, provider: str):
        super().__init__(f"no free {provider} slot")
        self.provider = provider


# ---------------------------------------------------------------------------
# Failure finalisation — shared with the scheduler's watchdog.

def requeue_run(db: SupabaseDataPlane, run_id: str, error: str) -> None:
    """The attempt failed but the job requeued: the run shows 'queued' again
    (users see queued, never a provider error — §9.3)."""
    db.set_run(run_id, status="queued", error=error[:2000])


def finalize_dlq(db: SupabaseDataPlane, org_id: str, run_id: str, error: str) -> dict:
    """Permanent system failure: run failed + automatic credit refund
    (reason refund.system_failure) + audit + ops alert (§10.3). Idempotent —
    safe under worker/watchdog double-fire."""
    db.set_run(run_id, finished=True, status="failed",
               error=f"system failure after retries: {error}"[:2000])
    refund = db.refund_credits(org_id, run_id)
    db.audit(org_id, None, "run.failed", f"analysis_run:{run_id}",
             {"error": error[:500], "dlq": True,
              "refunded": refund.get("refunded", 0)})
    logger.error("ALERT job.dlq", run_id=run_id, org_id=org_id,
                 error=error[:500], refunded=refund.get("refunded", 0))
    return refund

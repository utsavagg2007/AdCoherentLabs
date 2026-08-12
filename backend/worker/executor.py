"""Executes one leased job against the engine.saas data plane (§6.2 step 5).

Reuses the engine's own persistence verbatim — SupabaseDataPlane methods,
_apply_framework_entitlements, _persist_outcome — against the run row the API
pre-created.

Credits (0012): the API ESCROWED credits at enqueue; this process meters real
effort against that escrow as the engine works, and _persist_outcome settles
it — charging what was used and returning the rest. A DLQ'd job releases the
whole escrow (§10.3). The escrow is a hard ceiling, so nothing here can charge
more than the API reserved.

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
    if kinds in ({"pdf"}, {"docx"}, {"video"}):
        # Single-file kinds: engine.media converts them to the image/text
        # paths inside prepare_asset (media_workdir = this run's tmpdir).
        kind = next(iter(kinds))
        ext = Path(assets[0]["storage_path"]).suffix or f".{kind}"
        p = Path(tmpdir) / f"creative{ext}"
        p.write_bytes(storage.download_object_sync(assets[0]["storage_path"]))
        return {f"{kind}_path": str(p)}
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


def _meter_for(db: SupabaseDataPlane, run_id: str, org_id: str):
    """The billing sink handed to the engine: charges effort against this
    run's escrow the moment it happens, and hands back live headroom so the
    engine can stop before the escrow is gone."""
    def meter(unit: str, qty: float, meta: dict | None = None) -> dict:
        return db.meter_effort(org_id, run_id, unit, qty, meta)
    return meter


def _execute_fresh(db: SupabaseDataPlane, run: dict, ent, tmpdir: str):
    run_id, org_id = run["id"], run["org_id"]

    def emit(stage: str, event: str, message: str, detail: dict | None = None):
        db.emit_run_event(run_id, org_id, stage, event, message, detail)

    meter = _meter_for(db, run_id, org_id)

    emit("ingest", "ingest.loading",
         "Fetching your creative from secure storage.", {})
    engine_input = _load_input(db, run, tmpdir)
    input_kind = next(iter(engine_input)).removesuffix("_path")
    kind_label = {"image": "image", "text": "text", "html": "HTML",
                  "pdf": "PDF", "docx": "document",
                  "video": "video"}.get(input_kind, input_kind)
    emit("ingest", "ingest.ready",
         f"Creative loaded — analysing as {kind_label}.", {"kind": kind_label})

    db.set_run(run_id, status="running_cv", started=True)
    db.audit(org_id, run["created_by"], "run.started", f"analysis_run:{run_id}",
             {"tier": ent.tier, "model": ent.llm_model, "async": True})
    emit("cv", "cv.started",
         "Layer 1 — computer vision: OCR, layout geometry and visual "
         "measurements." if input_kind in ("image", "pdf", "video") else
         "Layer 1 — structuring the creative's text.", {})
    asset = prepare_asset(product_tier=ent.tier,
                          target_jurisdictions=run["target_jurisdictions"],
                          media_workdir=tmpdir,
                          meter=meter,
                          **engine_input)
    db.set_run(run_id, status="running_nlp")
    dropped = _apply_framework_entitlements(asset, ent)
    bypassed = dropped[:1] == ["__bypass__"]
    db.save_layer_output(run_id, org_id, "cv", {
        "provenance": asset.get("provenance", {}),
        "segments": len(asset.get("segments", []))})
    db.save_layer_output(run_id, org_id, "nlp", asset)
    frameworks = (asset.get("routing") or {}).get("frameworks") or []
    media_meta = (asset.get("provenance") or {}).get("media") or {}
    emit("nlp", "nlp.structured",
         (f"Layer 2 — language analysis: {len(asset.get('segments', []))} "
          f"segments, {len(asset.get('claim_candidates', []))} claim "
          f"candidates; routed to {len(frameworks)} regulatory "
          f"framework{'s' if len(frameworks) != 1 else ''}."),
         {"segments": len(asset.get("segments", [])),
          "claims": len(asset.get("claim_candidates", [])),
          "frameworks": frameworks, **({"media": media_meta} if media_meta else {})})

    db.set_run(run_id, status="running_llm")
    result = review_and_verify(asset, ent.tier,
                               max_llm_rounds=DEFAULT_MAX_LLM_ROUNDS,
                               progress=emit, meter=meter)

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
    re-OCR, so no Layer-1 effort, but the extra LLM round is real spend and is
    metered against this resume's own escrow (§8.1)."""
    run_id, org_id = run["id"], run["org_id"]

    def emit(stage: str, event: str, message: str, detail: dict | None = None):
        db.emit_run_event(run_id, org_id, stage, event, message, detail)

    meter = _meter_for(db, run_id, org_id)

    asset = db.load_asset_representation(run["resumed_from_run_id"])
    db.set_run(run_id, status="running_llm", started=True)
    db.audit(org_id, run["created_by"], "run.resumed", f"analysis_run:{run_id}",
             {"resumed_from": run["resumed_from_run_id"], "tier": ent.tier,
              "guidance_chars": len(run["operator_guidance"]), "async": True})
    emit("llm", "llm.resume",
         "Re-reviewing with your reviewer's guidance applied.", {})
    result = resume_with_human_guidance(
        asset, run["operator_guidance"], product_tier=ent.tier,
        progress=emit, meter=meter)
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

def requeue_run(db: SupabaseDataPlane, run_id: str, org_id: str,
                error: str) -> None:
    """The attempt failed but the job requeued: the run shows 'queued' again
    (users see queued, never a provider error — §9.3).

    The escrow stays (it was sized for one run and the run is still going),
    but its meter resets: the dead attempt's tokens are our cost, not the
    user's. Without the reset a run that retried twice would bill three
    attempts' worth of tokens for one report."""
    db.set_run(run_id, status="queued", error=error[:2000])
    db.reset_hold_meter(org_id, run_id)


def finalize_dlq(db: SupabaseDataPlane, org_id: str, run_id: str, error: str) -> dict:
    """Permanent system failure: run failed + full credit release + audit +
    ops alert (§10.3). Idempotent — safe under worker/watchdog double-fire.

    keep=0 is deliberate. The run burned real provider tokens before it died
    and those are metered in effort_events, but the failure is ours, so the
    user pays nothing. The difference is absorbed cost — which, unlike before
    0012, is now VISIBLE: effort_events holds the quantity and app.run_margin
    holds the dollars. Billing users for our own failures would be the wrong
    fix; not being able to see the bill was the actual problem."""
    db.set_run(run_id, finished=True, status="failed",
               error=f"system failure after retries: {error}"[:2000])

    release = db.release_hold(org_id, run_id, keep=0)
    if not release.get("released") and release.get("reason") == "no_hold":
        # Enqueued before 0012 deployed: no escrow, so reverse the flat charge
        # the old path took. Goes away when settle_run_tokens does.
        release = db.refund_credits(org_id, run_id)

    refunded = release.get("refunded", 0)
    db.audit(org_id, None, "run.failed", f"analysis_run:{run_id}",
             {"error": error[:500], "dlq": True, "refunded": refunded,
              "unbilled_effort": release.get("metered", 0)})
    logger.error("ALERT job.dlq", run_id=run_id, org_id=org_id,
                 error=error[:500], refunded=refunded,
                 unbilled_effort=release.get("metered", 0))
    return release

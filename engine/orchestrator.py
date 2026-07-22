"""The conductor: one ad in, one verified compliance result out.

Flow (the four layers, in order, synchronously):

    1. CV      cv/ via pipeline.analyze_asset — OCR (PaddleOCR on every
               product tier for now), geometry, markers
    2. NLP     nlp/ via the same call — segmentation, entities, claims,
               framework routing -> AssetRepresentation
    3. LLM+RAG adcoherent_rag.review — retrieve regulation chunks for
               the routed frameworks, tier's LLM reviews the ad
    4. RULES   rule_engine — deterministic verification of the review;
               on failure, calls Layer 3 back with fix instructions
               (max 2 callbacks after the initial call), then requests
               operator interference

The callback budget: ``DEFAULT_MAX_LLM_ROUNDS = 3`` total LLM calls =
1 initial + 2 rule-engine callbacks, per the product spec. A run that
exhausts the budget returns ``status="human_review"`` with the failed
checks and outstanding instructions; ``resume_with_human_guidance``
runs ONE more round with the operator's direction injected into the
prompt (repeat as often as the operator wants).
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import date
from typing import Any, Callable

from . import _paths  # noqa: F401  (sys.path bootstrap - must be first)

from pipeline import analyze_asset
from rule_engine.orchestrator import build_retry_payload, evaluate_with_retry

from . import media
from .llm_layer import LLMLayer, RagConnection
from .report import (
    EngineRunResult,
    HumanReviewRequest,
    RoundAudit,
    Verification,
)
from .tiers import get_tier, normalize_tier, ocr_tier_for

logger = logging.getLogger("engine")

#: Total LLM calls per run: 1 initial + 2 rule-engine callbacks.
DEFAULT_MAX_LLM_ROUNDS = 3

_RESUME_HINT = (
    "python -m engine.cli check ... --interactive  (prompts you for "
    "guidance and re-runs one LLM round), or call "
    "engine.resume_with_human_guidance(asset, guidance, tier=...) "
    "with your direction for the model"
)


def _new_run_id() -> str:
    return "run_" + uuid.uuid4().hex[:12]


def prepare_asset(
    *,
    asset_id: str | None = None,
    image_path: str | list[str] | None = None,
    text: str | None = None,
    html: str | None = None,
    pdf_path: str | None = None,
    docx_path: str | None = None,
    video_path: str | None = None,
    product_tier: str = "free",
    target_jurisdictions: list[str] | None = None,
    media_workdir: str | None = None,
) -> dict:
    """Layers 1+2: raw creative -> validated AssetRepresentation dict.

    Exactly one of image_path / text / html / pdf_path / docx_path /
    video_path. ``image_path`` may be a list (carousel ads). PDF pages
    and video keyframes convert to the multi-image path (engine.media);
    DOCX converts to the text path. ``media_workdir`` receives the
    intermediate page/frame files (a temp dir is created and cleaned up
    when omitted). The product tier only selects the OCR backend here
    (PaddleOCR for every tier, for now).
    """
    provided = [v is not None
                for v in (image_path, text, html, pdf_path, docx_path, video_path)]
    if sum(provided) != 1:
        raise ValueError("provide exactly one of image_path, text, html, "
                         "pdf_path, docx_path, or video_path")

    media_meta: dict | None = None
    workdir = media_workdir
    created_workdir = False
    if pdf_path is not None or video_path is not None:
        if workdir is None:
            import tempfile
            workdir = tempfile.mkdtemp(prefix="engine-media-")
            created_workdir = True

    try:
        if pdf_path is not None:
            image_path, media_meta = media.pdf_to_images(pdf_path, workdir)
        elif docx_path is not None:
            text, media_meta = media.docx_to_text(docx_path)
        elif video_path is not None:
            image_path, media_meta = media.video_to_frames(video_path, workdir)

        rep = analyze_asset(
            asset_id or ("ad_" + uuid.uuid4().hex[:12]),
            image_path=image_path,
            text=text,
            html=html,
            tier=ocr_tier_for(product_tier),
            target_jurisdictions=target_jurisdictions,
        )
    finally:
        if created_workdir:
            import shutil
            shutil.rmtree(workdir, ignore_errors=True)

    dump = rep.model_dump(mode="json")
    if media_meta:
        # Extra provenance key: survives the dict pipeline (layer_outputs,
        # report assembly); pydantic re-validation simply ignores it.
        dump.setdefault("provenance", {})["media"] = media_meta
    return dump


def review_and_verify(
    asset: dict,
    product_tier: str,
    *,
    max_llm_rounds: int = DEFAULT_MAX_LLM_ROUNDS,
    human_guidance: str | None = None,
    as_of: date | None = None,
    conn: Any = None,
    embedder: Any = None,
    retriever: Callable | None = None,
    provider: Any = None,
    manage_rag_connection: bool = True,
    resumed_from_run_id: str | None = None,
    include_asset: bool = False,
    progress: Callable[[str, str, str, dict], None] | None = None,
) -> EngineRunResult:
    """Layers 3+4 over a prepared asset: review, verify, callback loop.

    ``conn``/``embedder``/``retriever``/``provider`` are injectable (tests,
    stubs). When none are given and ``manage_rag_connection`` is True the
    production RAG store is wired from DATABASE_URL (degrading to empty
    retrieval with a warning when unreachable). ``progress`` receives
    sanitized (stage, event, message, detail) live-activity events.
    """
    tier_name = normalize_tier(product_tier)
    tier = get_tier(tier_name)
    run_id = _new_run_id()
    warnings: list[str] = []
    timings: dict[str, int] = {}

    def _emit(stage: str, event: str, message: str, detail: dict) -> None:
        if progress is None:
            return
        try:
            progress(stage, event, message, detail)
        except Exception:  # noqa: BLE001 — a broken sink never breaks a run
            logger.warning("progress sink failed for %s/%s", stage, event)

    rag: RagConnection | None = None
    if conn is None and retriever is None and manage_rag_connection:
        _emit("retrieval", "retrieval.connecting",
              "Connecting to the regulation corpus.", {})
        rag = RagConnection().connect()
        conn, embedder = rag.conn, rag.embedder
        warnings.extend(rag.warnings)
    frameworks = (asset.get("routing") or {}).get("frameworks") or []
    _emit("retrieval", "retrieval.ready",
          ("Regulation retrieval online — grounding the review for "
           f"{len(frameworks)} framework{'s' if len(frameworks) != 1 else ''}."
           if (conn is not None or retriever is not None)
           else "Running without regulation retrieval (degraded grounding)."),
          {"frameworks": frameworks,
           "online": bool(conn is not None or retriever is not None)})

    llm = LLMLayer(
        tier_name,
        conn=conn,
        embedder=embedder,
        retriever=retriever,
        provider=provider,
        target_jurisdictions=asset.get("target_jurisdictions") or None,
        as_of=as_of,
        human_guidance=human_guidance,
        progress=progress,
        max_rounds=max_llm_rounds,
    )

    t0 = time.monotonic()
    try:
        final = evaluate_with_retry(asset, llm, max_rounds=max_llm_rounds)
    finally:
        if rag is not None:
            rag.close()
    timings["review_and_verify"] = int((time.monotonic() - t0) * 1000)

    if final.final_report is not None:
        rep0 = final.final_report
        _emit("rules", "rules.final",
              (f"Deterministic verification complete — {len(rep0.results)} "
               f"checks run, {len(rep0.failed_checks)} failed.")
              if not rep0.passed else
              (f"Deterministic verification passed all "
               f"{len(rep0.results)} checks."),
              {"checks_run": len(rep0.results),
               "failed_checks": len(rep0.failed_checks),
               "passed": rep0.passed,
               "rounds_used": len(llm.rounds)})

    # ---- zip Layer-3 and Layer-4 audit trails ------------------------
    rounds: list[RoundAudit] = []
    for i, llm_round in enumerate(llm.rounds):
        rec = final.round_records[i] if i < len(final.round_records) else None
        rounds.append(RoundAudit(
            round=llm_round["round"],
            was_rule_engine_callback=llm_round["was_rule_engine_callback"],
            had_human_guidance=llm_round["had_human_guidance"],
            feedback_sent_to_llm=llm_round["feedback_sent_to_llm"],
            llm_review=llm_round["llm_review"],
            adapter_notes=llm_round["adapted_for_rule_engine"].get("adapter_notes", []),
            rule_engine_passed=(rec.report.passed if rec is not None else None),
            failed_checks=[c.model_dump(mode="json")
                           for c in (rec.report.failed_checks if rec is not None else [])],
        ))

    verification = None
    if final.final_report is not None:
        rep = final.final_report
        verification = Verification(
            review_passed=rep.passed,
            checks_run=len(rep.results),
            failed_checks=[c.model_dump(mode="json") for c in rep.failed_checks],
            asset_defects=[c.model_dump(mode="json") for c in rep.asset_defects],
            advisories=[c.model_dump(mode="json") for c in rep.advisories],
            ruleset_version=rep.ruleset_version,
            ruleset_hash=rep.ruleset_hash,
        )

    human_review = None
    if final.status == "human_review" and final.final_report is not None:
        instructions = build_retry_payload(final.final_report)
        human_review = HumanReviewRequest(
            reason=(f"The {tier_name}-tier LLM ({tier.model}) failed "
                    f"deterministic verification {final.rounds} time(s) "
                    f"(1 initial review + {final.rounds - 1} rule-engine "
                    f"callback(s)). A human must look at the scenario and "
                    f"prompt useful direction."),
            failed_checks=[c.model_dump(mode="json")
                           for c in final.final_report.failed_checks],
            instructions=[i.model_dump(mode="json") for i in instructions],
            how_to_resume=_RESUME_HINT,
        )

    final_review = llm.rounds[-1]["llm_review"] if llm.rounds else None
    provenance = {
        "tier": tier_name,
        "llm_provider": tier.provider,
        "llm_model": tier.model,
        "llm_effort": tier.effort,
        "prompt_version": (final_review or {}).get("llm_meta", {}).get("prompt_version"),
        "rag_corpus_hash": (final_review or {}).get("llm_meta", {}).get("rag_corpus_hash"),
        "rag_online": bool(conn is not None or retriever is not None),
        "ruleset_version": final.ruleset_version,
        "asset_provenance": asset.get("provenance", {}),
        "ocr_backend": (asset.get("provenance") or {}).get("ocr_backend"),
        "as_of": as_of.isoformat() if as_of else None,
    }

    return EngineRunResult(
        run_id=run_id,
        asset_id=str(asset.get("asset_id", "unknown")),
        tier=tier_name,
        status=final.status,
        llm_rounds_used=len(llm.rounds),
        max_llm_rounds=max_llm_rounds,
        llm_review=final_review,
        verification=verification,
        rounds=rounds,
        human_review=human_review,
        llm_error=final.llm_error,
        warnings=warnings,
        provenance=provenance,
        timings_ms=timings,
        resumed_from_run_id=resumed_from_run_id,
        asset=asset if include_asset else None,
    )


def run_compliance_engine(
    *,
    asset_id: str | None = None,
    image_path: str | list[str] | None = None,
    text: str | None = None,
    html: str | None = None,
    pdf_path: str | None = None,
    docx_path: str | None = None,
    video_path: str | None = None,
    product_tier: str = "free",
    target_jurisdictions: list[str] | None = None,
    as_of: date | None = None,
    max_llm_rounds: int = DEFAULT_MAX_LLM_ROUNDS,
    conn: Any = None,
    embedder: Any = None,
    retriever: Callable | None = None,
    provider: Any = None,
    include_asset: bool = False,
) -> EngineRunResult:
    """The whole engine, end to end: CV -> NLP -> RAG+LLM -> rules.

    Returns an EngineRunResult; ``result.asset`` carries the
    AssetRepresentation when ``include_asset`` (needed to resume a
    human_review run without re-OCRing).
    """
    t0 = time.monotonic()
    asset = prepare_asset(
        asset_id=asset_id,
        image_path=image_path,
        text=text,
        html=html,
        pdf_path=pdf_path,
        docx_path=docx_path,
        video_path=video_path,
        product_tier=product_tier,
        target_jurisdictions=target_jurisdictions,
    )
    prep_ms = int((time.monotonic() - t0) * 1000)
    logger.info("asset %s prepared in %dms (segments=%d claims=%d frameworks=%s)",
                asset["asset_id"], prep_ms, len(asset.get("segments", [])),
                len(asset.get("claim_candidates", [])),
                (asset.get("routing") or {}).get("frameworks"))

    result = review_and_verify(
        asset, product_tier,
        max_llm_rounds=max_llm_rounds,
        as_of=as_of,
        conn=conn, embedder=embedder, retriever=retriever, provider=provider,
        include_asset=include_asset,
    )
    result.timings_ms["prepare_asset"] = prep_ms
    return result


def resume_with_human_guidance(
    asset: dict,
    guidance: str,
    *,
    product_tier: str,
    previous: EngineRunResult | None = None,
    as_of: date | None = None,
    conn: Any = None,
    embedder: Any = None,
    retriever: Callable | None = None,
    provider: Any = None,
    include_asset: bool = False,
    progress: Callable[[str, str, str, dict], None] | None = None,
) -> EngineRunResult:
    """Operator interference: one more LLM round steered by a human.

    The guidance is injected into the review prompt as authoritative
    operator direction, the rule engine verifies the new output, and a
    fresh EngineRunResult is returned (linked to the previous run via
    ``resumed_from_run_id``). Call repeatedly until satisfied.
    """
    if not guidance or not guidance.strip():
        raise ValueError("guidance must be a non-empty operator prompt")
    return review_and_verify(
        asset, product_tier,
        max_llm_rounds=1,
        human_guidance=guidance,
        as_of=as_of,
        conn=conn, embedder=embedder, retriever=retriever, provider=provider,
        resumed_from_run_id=(previous.run_id if previous else None),
        include_asset=include_asset,
        progress=progress,
    )

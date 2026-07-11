"""Review orchestration: NLP result in, compliance-review JSON out.

    review_asset(nlp_result, "pro", conn=conn, embedder=get_embedder())

Steps: validate input -> retrieve regulation chunks per routed framework
(tier-budgeted) -> call the tier's LLM -> sanitize citations -> assemble
the final document in the sample_output-LLMresponse.json shape.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, timezone
from typing import Any

from .context import Retriever, build_context, default_retriever
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from .providers import ReviewProvider, get_provider
from .tiers import get_tier

logger = logging.getLogger(__name__)


class ReviewError(ValueError):
    """The NLP input is unusable for a review."""


def _validate_nlp_result(nlp_result: dict[str, Any]) -> None:
    if not isinstance(nlp_result, dict):
        raise ReviewError("NLP result must be a JSON object")
    if not nlp_result.get("asset_id"):
        raise ReviewError("NLP result is missing asset_id")
    routing = nlp_result.get("routing") or {}
    if not routing.get("frameworks"):
        raise ReviewError(
            "NLP result routing.frameworks is empty — nothing to review against"
        )
    if not nlp_result.get("segments") and not nlp_result.get("claim_candidates"):
        raise ReviewError("NLP result has neither segments nor claim_candidates")


def _known_ids(nlp_result: dict[str, Any]) -> tuple[set[str], set[str], set[str]]:
    segments = {s.get("segment_id") for s in nlp_result.get("segments", [])}
    entities = {e.get("entity_id") for e in nlp_result.get("entities", [])}
    claims = {c.get("claim_id") for c in nlp_result.get("claim_candidates", [])}
    return segments - {None}, entities - {None}, claims - {None}


def _sanitize_citations(payload: dict[str, Any], nlp_result: dict[str, Any]) -> None:
    """Drop cited ids that don't exist in the input (hallucination guard)."""
    seg_ids, ent_ids, claim_ids = _known_ids(nlp_result)
    for f in payload.get("findings", []):
        dropped = [i for i in f.get("cited_segment_ids", []) if i not in seg_ids]
        if dropped:
            logger.warning("finding %s cited unknown segment ids %s — dropped",
                           f.get("finding_id"), dropped)
            f["cited_segment_ids"] = [i for i in f["cited_segment_ids"] if i in seg_ids]
        dropped = [i for i in f.get("cited_entity_ids", []) if i not in ent_ids]
        if dropped:
            logger.warning("finding %s cited unknown entity ids %s — dropped",
                           f.get("finding_id"), dropped)
            f["cited_entity_ids"] = [i for i in f["cited_entity_ids"] if i in ent_ids]
        if f.get("claim_candidate_id") not in claim_ids | {None}:
            logger.warning("finding %s cited unknown claim id %r — nulled",
                           f.get("finding_id"), f.get("claim_candidate_id"))
            f["claim_candidate_id"] = None
    known = seg_ids | ent_ids | claim_ids
    cleared = payload.get("reviewed_clear", [])
    payload["reviewed_clear"] = [i for i in cleared if i in known]


def review_asset(
    nlp_result: dict[str, Any],
    tier_name: str,
    *,
    conn: Any = None,
    embedder: Any = None,
    retriever: Retriever = default_retriever,
    provider: ReviewProvider | None = None,
    jurisdictions: list[str] | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    """Run one compliance review; returns the LLM-response document.

    ``retriever`` and ``provider`` are injectable for testing; production
    callers pass only conn/embedder and the tier name.
    """
    _validate_nlp_result(nlp_result)
    tier = get_tier(tier_name)

    started = time.monotonic()
    ctx = build_context(
        nlp_result, tier,
        retriever=retriever, conn=conn, embedder=embedder,
        jurisdictions=jurisdictions, as_of=as_of,
    )
    logger.info(
        "review %s tier=%s model=%s frameworks=%s chunks=%d",
        nlp_result["asset_id"], tier.name, tier.model,
        ctx.frameworks, ctx.total_chunks,
    )

    user_prompt = build_user_prompt(nlp_result, ctx, tier.max_context_chars)
    provider = provider or get_provider(tier)
    result = provider.complete(tier, SYSTEM_PROMPT, user_prompt)
    _sanitize_citations(result.payload, nlp_result)

    latency_ms = int((time.monotonic() - started) * 1000)
    return {
        "asset_id": nlp_result["asset_id"],
        "findings": result.payload["findings"],
        "reviewed_clear": result.payload["reviewed_clear"],
        "frameworks_evaluated": result.payload["frameworks_evaluated"],
        "llm_meta": {
            "tier": tier.name,
            "model": result.model,
            "prompt_version": PROMPT_VERSION,
            "rag_corpus_hash": ctx.corpus_hash,
            "retrieved_chunks": ctx.total_chunks,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "max_output_tokens": tier.max_output_tokens,
            "reviewed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "latency_ms": latency_ms,
        },
    }

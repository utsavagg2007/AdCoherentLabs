"""Layer 3 as a callable: RAG retrieval + tier-routed LLM review.

``LLMLayer`` is the bridge the rule-engine orchestrator calls on every
round. Round 1 runs a plain review; on a callback (the rule engine
passing back a failed EngineReport) it renders the failed checks into
actionable feedback and re-reviews; operator guidance (the
human-interference path) rides the same feedback channel.

Retrieval wiring resolves in this order:
  1. an injected ``retriever`` (tests / stubs);
  2. offline mode — an empty retriever: the review still runs, the
     prompt tells the model no regulation text was retrieved and to
     answer ``needs_review`` where grounding matters;
  3. the production hybrid retriever over Postgres/pgvector
     (DATABASE_URL), with the MiniLM embedder (EMBEDDING_FAKE honored).

If production wiring is requested but the DB is unreachable, the layer
degrades to offline retrieval with a loud warning instead of failing
the run — the engine must always be able to produce a (clearly
flagged) review.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Callable

from . import _paths  # noqa: F401  (sys.path bootstrap - must be first)

from adcoherent_rag.review.engine import review_asset
from adcoherent_rag.review.providers import ReviewProvider, get_provider

from .adapter import (
    adapt_review_for_rule_engine,
    combine_feedback,
    render_human_guidance,
    render_rule_engine_feedback,
)
from .tiers import get_tier, normalize_tier

logger = logging.getLogger("engine.llm_layer")


def empty_retriever(conn: Any, embedder: Any, query: str, *, k: int,
                    frameworks: list[str] | None,
                    jurisdictions: list[str] | None,
                    as_of: date | None) -> list:
    """Offline retrieval: no corpus. The prompt marks every framework as
    'no regulation text retrieved' and instructs the model not to guess."""
    return []


def retrieval_jurisdictions(target_jurisdictions: list[str] | None) -> list[str] | None:
    """Corpus jurisdiction filter for an ad's targeting.

    The chunk filter is an exact match on ``jurisdiction`` — federal
    rows are tagged "US", state rows "US-XX". Targeting a state must
    therefore ALSO include "US", or every federal regulation would be
    filtered out. No targeting -> None -> no filter (search everything).
    """
    if not target_jurisdictions:
        return None
    juris = {str(j).strip().upper() for j in target_jurisdictions if str(j).strip()}
    juris.add("US")
    return sorted(juris)


class RagConnection:
    """Lazily-resolved production RAG wiring (DB connection + embedder)."""

    def __init__(self) -> None:
        self.conn: Any = None
        self.embedder: Any = None
        self.warnings: list[str] = []
        self.online = False

    def connect(self) -> "RagConnection":
        from adcoherent_rag import config as rag_config

        if not rag_config.DATABASE_URL:
            self.warnings.append(
                "DATABASE_URL is not set - running with EMPTY regulation "
                "retrieval (the LLM is told it has no rule text; verdicts "
                "lean on needs_review). Set DATABASE_URL and ingest the "
                "corpus for grounded reviews.")
            return self
        try:
            from adcoherent_rag.embed.embedder import get_embedder
            from adcoherent_rag.store.db import get_connection

            self.conn = get_connection()
            self.embedder = get_embedder()
            self.online = True
        except Exception as exc:  # degrade, never die: reviews must run
            self.warnings.append(
                f"RAG store unreachable ({type(exc).__name__}: {exc}) - "
                "running with EMPTY regulation retrieval.")
        return self

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
            self.conn = None
            self.online = False


class LLMLayer:
    """The ``get_llm_output`` callable handed to evaluate_with_retry.

    Records, per round: the ORIGINAL review document (product format,
    verdicts unmapped), the adapted document handed to the rule engine,
    and the feedback string that produced the round. ``rounds`` is the
    Layer-3 side of the audit trail; the orchestrator zips it with the
    rule engine's round records.
    """

    def __init__(
        self,
        tier_name: str,
        *,
        conn: Any = None,
        embedder: Any = None,
        retriever: Callable | None = None,
        provider: ReviewProvider | None = None,
        target_jurisdictions: list[str] | None = None,
        as_of: date | None = None,
        human_guidance: str | None = None,
    ) -> None:
        self.tier_name = normalize_tier(tier_name)
        self.tier = get_tier(self.tier_name)
        self.conn = conn
        self.embedder = embedder
        self.retriever = retriever
        self.provider = provider  # resolved lazily per tier when None
        self.jurisdictions = retrieval_jurisdictions(target_jurisdictions)
        self.as_of = as_of
        self.human_guidance = human_guidance
        self.rounds: list[dict[str, Any]] = []

    def _resolve_provider(self) -> ReviewProvider:
        if self.provider is None:
            self.provider = get_provider(self.tier)
        return self.provider

    def _resolve_retriever(self) -> Callable:
        if self.retriever is not None:
            return self.retriever
        if self.conn is None:
            logger.warning("no RAG store wired - reviewing with empty retrieval")
            return empty_retriever
        from adcoherent_rag.review.context import default_retriever

        return default_retriever

    def __call__(self, asset: dict, prior_report: Any = None) -> dict:
        """One Layer-3 round. ``prior_report`` is the failed EngineReport
        on a rule-engine callback (None on the first round)."""
        from rule_engine.orchestrator import build_retry_payload

        engine_feedback = None
        if prior_report is not None:
            instructions = build_retry_payload(prior_report)
            engine_feedback = render_rule_engine_feedback(instructions)
        guidance = (render_human_guidance(self.human_guidance)
                    if self.human_guidance else None)
        feedback = combine_feedback(engine_feedback, guidance)

        round_no = len(self.rounds) + 1
        logger.info("LLM round %d (tier=%s model=%s callback=%s guidance=%s)",
                    round_no, self.tier_name, self.tier.model,
                    prior_report is not None, bool(guidance))

        review_doc = review_asset(
            asset,
            self.tier_name,
            conn=self.conn,
            embedder=self.embedder,
            retriever=self._resolve_retriever(),
            provider=self._resolve_provider(),
            jurisdictions=self.jurisdictions,
            as_of=self.as_of,
            feedback=feedback,
        )
        adapted = adapt_review_for_rule_engine(review_doc)
        self.rounds.append({
            "round": round_no,
            "was_rule_engine_callback": prior_report is not None,
            "had_human_guidance": bool(guidance),
            "feedback_sent_to_llm": feedback,
            "llm_review": review_doc,
            "adapted_for_rule_engine": adapted,
        })
        return adapted

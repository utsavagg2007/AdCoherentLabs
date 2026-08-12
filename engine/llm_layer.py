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


class BudgetExhausted(Exception):
    """The run's escrowed credits ran out; no further LLM round may start.

    Raised BEFORE a round's provider call, never during one — a round that has
    already spent tokens always completes and is always metered. Round 1 is
    never blocked: the reserve is guaranteed to cover the floor, so every run
    produces at least one review.

    evaluate_with_retry catches this like any other LLM-layer failure and
    returns status='llm_error' with the completed rounds preserved;
    review_and_verify then reclassifies it as a budget stop rather than a
    system failure, so it never triggers the DLQ refund path.
    """

    def __init__(self, rounds_done: int, metered: float, reserved: int):
        super().__init__(
            f"credit budget exhausted after {rounds_done} round(s): "
            f"metered {metered} of {reserved} reserved credits")
        self.rounds_done = rounds_done
        self.metered = metered
        self.reserved = reserved


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
        progress: Callable[[str, str, str, dict], None] | None = None,
        meter: Callable[[str, float, dict], dict] | None = None,
        max_rounds: int | None = None,
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
        self.progress = progress          # (stage, event, message, detail) — sanitized
        self.meter = meter                # (unit, qty, meta) -> headroom reading
        self.max_rounds = max_rounds
        self.rounds: list[dict[str, Any]] = []
        #: Set once metering reports the escrow is spent. The next round
        #: refuses to start; the orchestrator reads this to distinguish a
        #: budget stop from a provider failure.
        self.budget_stopped = False
        self.last_reading: dict[str, Any] = {}

    def _emit(self, stage: str, event: str, message: str, detail: dict) -> None:
        """Progress events carry TEMPLATES + COUNTS only — never ad text,
        retrieved regulation chunks, prompts, or model reasoning. A broken
        sink must never break a run."""
        if self.progress is None:
            return
        try:
            self.progress(stage, event, message, detail)
        except Exception:  # noqa: BLE001
            logger.warning("progress sink failed for %s/%s", stage, event)

    def _meter(self, unit: str, qty: float, **meta: Any) -> dict:
        """Charge `qty` of `unit` against the run's hold, right now.

        Metering failures degrade to UNMETERED, never to a failed run: a
        billing outage must not cost a paying user their report. The
        consequence is absorbed cost on our side, which is the correct way
        round for this trade — and effort_events still records the attempt."""
        if self.meter is None:
            return {}
        try:
            reading = self.meter(unit, float(qty), meta) or {}
        except Exception:  # noqa: BLE001 — a broken meter never breaks a run
            logger.warning("meter sink failed for %s (qty=%s)", unit, qty)
            return {}
        self.last_reading = reading
        if reading.get("exhausted"):
            self.budget_stopped = True
        return reading

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

        # Budget gate — checked here, before any provider call, so the escrow
        # bounds spend to at most one round of overrun rather than all three.
        # Never applies to round 1: the reserve covers the floor by
        # construction, and a run that produces no review at all is worse for
        # the user than a run that slightly overruns for us.
        if self.budget_stopped and self.rounds:
            raise BudgetExhausted(len(self.rounds),
                                  float(self.last_reading.get("metered") or 0),
                                  int(self.last_reading.get("reserved") or 0))

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

        rounds_of = f"{round_no}/{self.max_rounds}" if self.max_rounds else str(round_no)
        if prior_report is not None:
            failed_n = len(getattr(prior_report, "failed_checks", []) or [])
            self._emit("rules", "rules.callback",
                       f"Deterministic verification flagged {failed_n} "
                       f"check{'s' if failed_n != 1 else ''} — sending fix "
                       "instructions back to the model.",
                       {"failed_checks": failed_n, "round": round_no})
        self._emit("llm", "llm.round_started",
                   f"Review round {rounds_of} — grounded model review "
                   f"of {len(asset.get('claim_candidates', []))} claim "
                   "candidates in progress.",
                   {"round": round_no, "max_rounds": self.max_rounds,
                    "callback": prior_report is not None,
                    "guided": bool(guidance)})

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

        # Meter this round's tokens NOW, not at the end of the run. The user's
        # balance moves while the run is still going, and the reading below is
        # what stops round N+1 from starting if the escrow is spent.
        llm_meta = (review_doc or {}).get("llm_meta") or {}
        round_in = int(llm_meta.get("input_tokens") or 0)
        round_out = int(llm_meta.get("output_tokens") or 0)
        self._meter("llm_call", 1, round=round_no, model=llm_meta.get("model"))
        if round_in:
            self._meter("llm_input_1k", round_in / 1000.0,
                        round=round_no, model=llm_meta.get("model"))
        reading = self._meter("llm_output_1k", round_out / 1000.0,
                              round=round_no, model=llm_meta.get("model")) \
            if round_out else self.last_reading

        findings_n = len((review_doc or {}).get("findings") or [])
        self._emit("llm", "llm.round_done",
                   f"Round {rounds_of} returned {findings_n} "
                   f"finding{'s' if findings_n != 1 else ''}; handing off "
                   "to deterministic verification.",
                   {"round": round_no, "findings": findings_n,
                    "input_tokens": round_in, "output_tokens": round_out})
        if reading.get("billed"):
            # Live credit line in the user's activity feed — the visible half
            # of "deducted in real time".
            spent = float(reading.get("metered") or 0)
            self._emit("llm", "llm.credits_metered",
                       f"Round {rounds_of} used {round_in + round_out:,} "
                       f"tokens — {spent:.2f} credits of "
                       f"{reading.get('reserved')} reserved used so far.",
                       {"round": round_no,
                        "metered": spent,
                        "reserved": reading.get("reserved"),
                        "headroom": reading.get("headroom")})
        if self.budget_stopped:
            self._emit("llm", "llm.budget_reached",
                       "Reserved credits for this run are used up — "
                       "finishing with the review completed so far.",
                       {"round": round_no,
                        "metered": float(reading.get("metered") or 0),
                        "reserved": reading.get("reserved")})
        self.rounds.append({
            "round": round_no,
            "was_rule_engine_callback": prior_report is not None,
            "had_human_guidance": bool(guidance),
            "feedback_sent_to_llm": feedback,
            "llm_review": review_doc,
            "adapted_for_rule_engine": adapted,
        })
        return adapted

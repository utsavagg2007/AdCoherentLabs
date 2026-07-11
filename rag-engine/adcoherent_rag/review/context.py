"""Retrieval context for a review: NLP frameworks -> corpus chunks.

The NLP router emits framework labels like "TILA" or "CFPB"; the corpus
tags chunks with the labels produced by manifest.frameworks_for (Reg_Z,
UDAAP, ...). NLP_FRAMEWORK_ALIASES bridges the two — the original NLP
label is preserved for the LLM/output, the alias drives the retrieval
filter.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Protocol

from ..models import RetrievalResult
from .tiers import TierConfig

logger = logging.getLogger(__name__)

# NLP label -> corpus framework tag (see manifest.FRAMEWORK_MAP values).
# Statute names map onto their implementing regulation; "CFPB" as a bare
# label means the UDAAP statute corpus.
NLP_FRAMEWORK_ALIASES: dict[str, str] = {
    "TILA": "Reg_Z",
    "REG_Z": "Reg_Z",
    "TISA": "Reg_DD",
    "REG_DD": "Reg_DD",
    "ECOA": "Reg_B",
    "REG_B": "Reg_B",
    "CLA": "Reg_M",
    "REG_M": "Reg_M",
    "MAP": "Reg_N",
    "REG_N": "Reg_N",
    "CFPB": "UDAAP",
    "UDAAP": "UDAAP",
    "FTC": "FTC",
    "CAN_SPAM": "CAN_SPAM",
    "COPPA": "COPPA",
    "FDIC": "FDIC",
    "NCUA": "NCUA",
    "SEC": "SEC",
    "FINRA": "FINRA",
    "TCPA": "TCPA",
    "FHA": "FHA",
    "STATE_UDAP": "STATE_UDAP",
}


class Retriever(Protocol):
    def __call__(self, conn: Any, embedder: Any, query: str, *, k: int,
                 frameworks: list[str] | None, jurisdictions: list[str] | None,
                 as_of: date | None) -> list[RetrievalResult]: ...


@dataclass
class ReviewContext:
    frameworks: list[str]                                # NLP labels, order kept
    chunks_by_framework: dict[str, list[RetrievalResult]] = field(default_factory=dict)

    @property
    def corpus_hash(self) -> str:
        """Stable fingerprint of the regulation versions the review saw."""
        version_ids = sorted(
            {c.version_id for chunks in self.chunks_by_framework.values() for c in chunks}
        )
        if not version_ids:
            return "empty"
        return hashlib.sha256("|".join(version_ids).encode()).hexdigest()[:16]

    @property
    def total_chunks(self) -> int:
        return sum(len(v) for v in self.chunks_by_framework.values())


def corpus_framework_for(nlp_label: str) -> str:
    """Map an NLP routing label to the corpus tag; unknown labels pass through."""
    return NLP_FRAMEWORK_ALIASES.get(nlp_label.strip().upper().replace(" ", "_"),
                                     nlp_label.strip())


def build_queries(nlp_result: dict[str, Any]) -> list[str]:
    """Retrieval queries for one asset.

    Claim candidates are the primary hook (they are what the review is
    about); headline/disclosure/CTA segments are added so disclosure-
    adequacy rules are retrieved even when no claim was extracted. The
    routing signal is included as a corpus-vocabulary bridge.
    """
    queries: list[str] = []
    seen: set[str] = set()

    def _add(text: str | None) -> None:
        text = " ".join((text or "").split())
        if text and text.lower() not in seen:
            seen.add(text.lower())
            queries.append(text)

    for claim in nlp_result.get("claim_candidates", []):
        _add(claim.get("text"))
    for seg in nlp_result.get("segments", []):
        if seg.get("role") in ("headline", "subheadline", "disclosure", "cta"):
            _add(seg.get("text"))
    _add((nlp_result.get("routing") or {}).get("signal"))
    return queries


def build_context(
    nlp_result: dict[str, Any],
    tier: TierConfig,
    *,
    retriever: Retriever,
    conn: Any,
    embedder: Any,
    jurisdictions: list[str] | None = None,
    as_of: date | None = None,
) -> ReviewContext:
    """Retrieve, per NLP framework, the chunks the LLM will review against."""
    frameworks = list((nlp_result.get("routing") or {}).get("frameworks") or [])
    ctx = ReviewContext(frameworks=frameworks)
    queries = build_queries(nlp_result)

    for nlp_label in frameworks:
        corpus_label = corpus_framework_for(nlp_label)
        collected: list[RetrievalResult] = []
        seen_chunks: set[str] = set()
        for query in queries:
            if len(collected) >= tier.max_chunks_per_framework:
                break
            results = retriever(
                conn, embedder, query,
                k=tier.chunks_per_query,
                frameworks=[corpus_label],
                jurisdictions=jurisdictions,
                as_of=as_of,
            )
            for r in results:
                if r.chunk_id not in seen_chunks:
                    seen_chunks.add(r.chunk_id)
                    collected.append(r)
        ctx.chunks_by_framework[nlp_label] = collected[: tier.max_chunks_per_framework]
        if not collected:
            logger.warning(
                "no corpus chunks for framework %r (corpus label %r) — "
                "the LLM will be told this framework has no retrieved text",
                nlp_label, corpus_label,
            )
    return ctx


# Convenience default that binds the production hybrid retriever lazily so
# importing this module never requires psycopg/pgvector at import time.
def default_retriever(conn: Any, embedder: Any, query: str, *, k: int,
                      frameworks: list[str] | None, jurisdictions: list[str] | None,
                      as_of: date | None) -> list[RetrievalResult]:
    from ..retrieval.hybrid import retrieve

    return retrieve(conn, embedder, query, k=k, frameworks=frameworks,
                    jurisdictions=jurisdictions, as_of=as_of)


DefaultRetriever: Callable[..., list[RetrievalResult]] = default_retriever

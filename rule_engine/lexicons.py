"""Versioned lexicons, thresholds, and pure helpers for framework checks.

Compiled form of docs/check_taxonomy.md Appendix A (lexicons) and
Appendix B (thresholds), plus small deterministic predicates shared by
the framework check modules. Regulatory text was interpreted once, at
authoring time, into these constants — editing any of them is a ruleset
version bump, and the whole table belongs in the ruleset_hash payload.

Determinism guard (see rule_engine/core.py): stdlib only.
"""

from __future__ import annotations

import re

LEXICON_VERSION = "v1"
THRESHOLDS_VERSION = "v1"

# --- Appendix B thresholds (NUM_TOL lives with ALL-GRD-007) ---------------
PROX_MAX = 0.60             # max claim->disclosure bbox-center distance
HEIGHT_MIN_PCT = 0.9        # min disclosure text height, % of asset height
APR_HEIGHT_RATIO_MIN = 0.33  # min APR-disclosure/trigger text-height ratio

# --- Product groupings ----------------------------------------------------
CREDIT_PRODUCTS = frozenset(
    {"credit_card", "personal_loan", "mortgage", "auto_loan", "bnpl"}
)
CLOSED_END_PRODUCTS = frozenset(
    {"personal_loan", "mortgage", "auto_loan", "bnpl"}
)
OPEN_END_PRODUCTS = frozenset({"credit_card", "bnpl"})
UNINSURABLE_PRODUCTS = frozenset({"investment", "crypto", "insurance"})

# --- Appendix A lexicons (v1) ----------------------------------------------
# `everyone('s| is) approved` from the taxonomy is expanded to literals.
LEXICONS: dict[str, tuple[str, ...]] = {
    "APR": ("apr", "annual percentage rate"),
    "APY": ("apy", "annual percentage yield"),
    "TILA_TRIGGER": ("per month", "/mo", "a month", "monthly payment",
                     "payments of", "down payment", "no money down",
                     "-month term", "month term", "weekly payment"),
    "FDIC": ("fdic", "member fdic", "fdic insured", "fdic-insured",
             "federally insured", "deposit insurance"),
    "DEPOSIT_TERMS": ("apy", "annual percentage yield", "interest rate",
                      "interest", "bonus", "minimum balance", "fee",
                      "compounded"),
    "FREE_ACCOUNT": ("free", "no fee", "no fees", "no monthly fee",
                     "no hidden fees", "zero fees", "no cost"),
    "BONUS": ("bonus", "sign-up bonus", "signup bonus", "welcome bonus"),
    "NON_DEPOSIT_DISCLAIMER": ("not fdic insured", "not fdic-insured",
                               "may lose value", "not bank guaranteed",
                               "no bank guarantee",
                               "not insured by any federal government agency"),
    "INVESTMENT": ("invest", "investment", "securities", "stocks", "crypto",
                   "bitcoin", "portfolio", "returns"),
    "GUARANTEED_APPROVAL": ("guaranteed approval", "approval guaranteed",
                            "guarantee approval", "no credit check",
                            "everyone qualifies", "no one refused",
                            "everyone's approved", "everyone is approved"),
    "PROHIBITED_BASIS": ("race", "religion", "national origin",
                         "marital status", "public assistance"),
}

_COMPILED: dict[str, re.Pattern] = {}


def norm(text: str) -> str:
    """Whitespace normalization: collapse runs; no other transformation."""
    return " ".join(text.split())


def _pattern(name: str) -> re.Pattern:
    if name not in _COMPILED:
        parts = []
        # Longest-first so multi-word members win over their prefixes.
        for member in sorted(LEXICONS[name], key=len, reverse=True):
            lead = r"\b" if member[0].isalnum() else ""
            tail = r"\b" if member[-1].isalnum() else ""
            parts.append(lead + re.escape(member) + tail)
        _COMPILED[name] = re.compile("|".join(parts), re.IGNORECASE)
    return _COMPILED[name]


def match_lexicon(name: str, text: str) -> list[str]:
    """Matched lexemes (lowercased, deduped, in match order) in text."""
    seen: dict[str, None] = {}
    for m in _pattern(name).findall(norm(text)):
        seen.setdefault(m.lower())
    return list(seen)


def segments_matching(ctx, name: str) -> list[tuple[object, list[str]]]:
    """(segment, matched lexemes) for every segment the lexicon hits."""
    out = []
    for s in ctx.asset.segments:
        matches = match_lexicon(name, s.text)
        if matches:
            out.append((s, matches))
    return out


def covered_ids(llm) -> frozenset[str]:
    """taxonomy covered(id): every id any finding cites + reviewed_clear."""
    ids = set(llm.reviewed_clear)
    for f in llm.findings:
        ids.update(f.cited_segment_ids)
        ids.update(f.cited_entity_ids)
        if f.claim_candidate_id:
            ids.add(f.claim_candidate_id)
    return frozenset(ids)


def heights_by_segment(ctx) -> dict[str, float]:
    """segment_id -> text_height_percent from the CV findings."""
    return {f.segment_id: f.value for f in ctx.asset.cv_findings
            if f.measurement.value == "text_height_percent" and f.segment_id}


def proximity_findings(ctx) -> list:
    """All disclosure_proximity CV findings (claim seg -> related seg)."""
    return [f for f in ctx.asset.cv_findings
            if f.measurement.value == "disclosure_proximity"
            and f.segment_id and f.related_segment_id]


def entities_of_type(ctx, *types: str) -> list:
    return [e for e in ctx.asset.entities if e.entity_type.value in types]


def entity_evidence(entities) -> list[dict]:
    return [{"entity_id": e.entity_id, "type": e.entity_type.value,
             "raw_text": e.raw_text, "segment_id": e.segment_id,
             "char_span": [e.char_span.start, e.char_span.end]}
            for e in entities]

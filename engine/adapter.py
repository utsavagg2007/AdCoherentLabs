"""Contract bridge: RAG review document <-> rule-engine LLMOutput.

The two repos evolved two dialects of the same document:

  * the RAG review layer (adcoherent_rag.review.schema) emits verdicts
    ``potential_violation | needs_review | compliant`` plus two extra
    per-finding fields (``regulation_citations``, ``scope_of_improvement``);
  * the rule engine (llm_contract.LLMOutput) validates verdicts
    ``violation | potential_violation | compliant`` and a ``framework``
    that must be a ``schema.Framework`` enum value.

``adapt_review_for_rule_engine`` produces a deep copy that the rule
engine will validate: ``needs_review`` maps to ``potential_violation``
(both mean "needs a human or more evidence" per the contract docstring),
framework labels are coerced onto enum values, and findings whose
framework cannot be coerced are dropped (loudly, into adapter_notes —
dropping coverage will then surface deterministically as a rule-engine
coverage failure, which feeds the retry loop rather than crashing it).
The ORIGINAL document is never mutated: it is what the product stores
and shows (it carries scope_of_improvement / regulation_citations).

This module also renders the rule engine's retry instructions and any
operator (human) guidance into the ``feedback`` string that
``review_asset`` injects into the LLM prompt on callbacks.
"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any

from . import _paths  # noqa: F401  (sys.path bootstrap - must be first)

from schema import Framework

if TYPE_CHECKING:  # imported lazily at runtime by callers
    from rule_engine.orchestrator import RetryInstruction

logger = logging.getLogger("engine.adapter")

#: RAG verdict -> rule-engine verdict. Only the divergent value maps;
#: identical values pass through.
VERDICT_MAP: dict[str, str] = {"needs_review": "potential_violation"}

_FRAMEWORK_BY_KEY: dict[str, str] = {}
for _f in Framework:
    for _alias in {_f.value, _f.name}:
        _FRAMEWORK_BY_KEY[_alias.upper().replace("-", "_").replace(" ", "_")] = _f.value


def coerce_framework(value: Any) -> str | None:
    """Map an LLM-written framework label onto a Framework enum value.

    Exact enum values pass through; otherwise match case-insensitively
    with ``-``/`` `` treated as ``_`` (so "Reg DD", "reg_dd", "CAN_SPAM"
    all resolve). Returns None when nothing matches.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    return _FRAMEWORK_BY_KEY.get(value.strip().upper().replace("-", "_").replace(" ", "_"))


def adapt_review_for_rule_engine(review_doc: dict[str, Any]) -> dict[str, Any]:
    """Deep-copied, rule-engine-valid version of a RAG review document.

    Adds ``adapter_notes`` (verdict remaps, dropped findings) so the run
    audit records every transformation between the layers. Extra RAG
    fields (regulation_citations, scope_of_improvement) are left in
    place — pydantic ignores unknown keys on validation.
    """
    doc = copy.deepcopy(review_doc)
    notes: list[dict[str, Any]] = []

    kept: list[dict[str, Any]] = []
    for finding in doc.get("findings", []):
        fid = finding.get("finding_id")

        verdict = finding.get("verdict")
        if verdict in VERDICT_MAP:
            finding["verdict"] = VERDICT_MAP[verdict]
            notes.append({"finding_id": fid, "action": "verdict_remapped",
                          "from": verdict, "to": finding["verdict"]})

        coerced = coerce_framework(finding.get("framework"))
        if coerced is None:
            logger.warning(
                "finding %s names unknown framework %r - dropped for the "
                "rule engine (coverage checks will flag any resulting gap)",
                fid, finding.get("framework"))
            notes.append({"finding_id": fid, "action": "dropped_unknown_framework",
                          "framework": finding.get("framework")})
            continue
        if coerced != finding.get("framework"):
            notes.append({"finding_id": fid, "action": "framework_coerced",
                          "from": finding.get("framework"), "to": coerced})
            finding["framework"] = coerced
        kept.append(finding)
    doc["findings"] = kept

    evaluated: list[str] = []
    for label in doc.get("frameworks_evaluated", []):
        coerced = coerce_framework(label)
        evaluated.append(coerced if coerced is not None else label)
    # de-dup, order-preserving (coercion can collapse two spellings)
    doc["frameworks_evaluated"] = list(dict.fromkeys(evaluated))

    doc["adapter_notes"] = notes
    return doc


def render_rule_engine_feedback(instructions: list["RetryInstruction"]) -> str:
    """Rule-engine retry instructions -> feedback text for the LLM prompt."""
    lines = [
        "Your previous review FAILED the deterministic rule engine's "
        "verification. Fix every item below and return a corrected, "
        "complete review (the full JSON document, not a diff):",
        "",
    ]
    for i, ins in enumerate(instructions, 1):
        lines.append(f"{i}. [{ins.check_id} | severity={ins.severity}] {ins.message}")
        lines.append(f"   Required fix: {ins.instruction}")
    return "\n".join(lines)


def render_human_guidance(guidance: str) -> str:
    """Operator guidance -> feedback text for the LLM prompt."""
    return (
        "OPERATOR GUIDANCE (a human compliance reviewer inspected the "
        "previous rounds; follow this direction, it overrides your prior "
        "output where they conflict):\n\n" + guidance.strip()
    )


def combine_feedback(*parts: str | None) -> str | None:
    """Join non-empty feedback sections with a blank line; None when empty."""
    chunks = [p.strip() for p in parts if p and p.strip()]
    return "\n\n".join(chunks) if chunks else None

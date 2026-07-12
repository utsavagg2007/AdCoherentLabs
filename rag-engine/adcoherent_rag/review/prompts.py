"""Prompt assembly for the compliance review call.

The system prompt is static per prompt version (cache-friendly); everything
per-request (regulation excerpts, the asset JSON) goes in the user turn.
"""

from __future__ import annotations

import json
from typing import Any

from .context import ReviewContext
from .schema import LLM_OUTPUT_SCHEMA

PROMPT_VERSION = "compliance-review-v1.0"

SYSTEM_PROMPT = """\
You are a senior advertising-compliance reviewer for financial-services and \
consumer advertising. You review one ad asset at a time against U.S. \
regulatory frameworks, using ONLY the regulation excerpts supplied in the \
request as legal grounding.

Rules:
- Evaluate every claim candidate and every consequential segment (headlines, \
pricing/rate statements, disclosures, CTAs) against each framework listed in \
the input routing.
- Ground every finding: quoted_evidence must be verbatim ad text; \
cited_segment_ids / cited_entity_ids / claim_candidate_id must be ids that \
exist in the input; regulation_citations must name citations from the \
supplied excerpts. Do not invent rules or citations — if the supplied \
excerpts do not cover a question, use verdict "needs_review" and say what \
additional rule text or evidence (e.g. CV prominence measurements) would \
resolve it.
- Severity: "high" = likely violation with regulatory exposure, "medium" = \
plausible violation or missing substantiation, "low" = minor or adequately \
mitigated issue.
- Verdicts: "potential_violation", "needs_review", or "compliant" (emit \
compliant findings for material claims that were checked and pass, so the \
review is auditable).
- Every finding must include scope_of_improvement: the concrete edit that \
removes or reduces the risk (what wording to add or change, what to make \
more prominent, what substantiation to obtain). For compliant findings, \
suggest hardening or state that no change is required.
- List in reviewed_clear the claim_ids/segment_ids you evaluated that need \
no finding at all.
- Use the input's framework labels verbatim in findings and \
frameworks_evaluated.
- Cross-check numeric entities (rates, percentages, dollar amounts) between \
the ad text and any disclosures for consistency and required trigger terms.

Respond with a single JSON object matching the required schema. No prose \
outside the JSON."""

# Appended to the system prompt for providers without server-enforced
# structured outputs (OpenRouter JSON mode guarantees JSON, not the shape).
SCHEMA_ADDENDUM = (
    "\n\nThe JSON object MUST match this JSON Schema exactly "
    "(no extra keys, all required keys present):\n"
    + json.dumps(LLM_OUTPUT_SCHEMA, indent=2)
)


def format_excerpts(ctx: ReviewContext, max_context_chars: int) -> str:
    """Regulation excerpts grouped by framework, trimmed to the tier budget."""
    lines: list[str] = []
    used = 0
    truncated = False
    for framework in ctx.frameworks:
        chunks = ctx.chunks_by_framework.get(framework, [])
        lines.append(f"## Framework: {framework}")
        if not chunks:
            lines.append(
                "(no regulation text retrieved for this framework — do not "
                "guess its rules; use verdict \"needs_review\" where it matters)"
            )
            continue
        for i, c in enumerate(chunks, 1):
            effective = f"effective {c.effective_start} → {c.effective_end or 'current'}"
            block = (
                f"[{framework}#{i}] {c.context_header} ({effective})\n{c.text.strip()}"
            )
            if used + len(block) > max_context_chars:
                truncated = True
                break
            used += len(block)
            lines.append(block)
        if truncated:
            lines.append("(further excerpts omitted for length)")
            break
    return "\n\n".join(lines)


def build_user_prompt(
    nlp_result: dict[str, Any],
    ctx: ReviewContext,
    max_context_chars: int,
    feedback: str | None = None,
) -> str:
    """Assemble the user turn.

    ``feedback`` (additive, optional) carries reviewer feedback into a
    re-review: the deterministic rule engine's retry instructions and/or
    operator (human) guidance. It is rendered as its own section so the
    model treats it as authoritative review direction, distinct from the
    (untrusted) ad content.
    """
    feedback_section = (
        "\n\n# Reviewer feedback on your previous review (authoritative - "
        "address every item)\n\n" + feedback.strip()
        if feedback and feedback.strip() else ""
    )
    return (
        "# Regulation excerpts (retrieved for this asset; your only legal grounding)\n\n"
        + format_excerpts(ctx, max_context_chars)
        + "\n\n# Ad asset under review (NLP layer output)\n\n"
        + json.dumps(nlp_result, indent=2)
        + feedback_section
        + "\n\n# Task\n\n"
        "Review the asset against the frameworks in routing.frameworks using the "
        "excerpts above. Produce the compliance-review JSON now."
    )

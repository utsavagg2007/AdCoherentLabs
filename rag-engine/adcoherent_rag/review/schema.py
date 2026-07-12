"""LLM output contract: JSON schema + validation.

The LLM returns only what it can reason about (findings, reviewed_clear,
frameworks_evaluated); the engine adds asset_id and llm_meta so the final
document matches sample_output-LLMresponse.json.

Two additions over the sample:
  scope_of_improvement   per finding — required by product spec: a concrete
                         edit that removes or reduces the compliance risk
  regulation_citations   per finding — which retrieved regulation citations
                         support the finding (audit traceability)

The schema follows structured-outputs constraints (additionalProperties
false everywhere, no min/max length keywords) so it can be passed verbatim
as an Anthropic json_schema output format.
"""

from __future__ import annotations

from typing import Any

SEVERITIES = ("high", "medium", "low")
VERDICTS = ("potential_violation", "needs_review", "compliant")

_FINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "finding_id": {
            "type": "string",
            "description": "Sequential id: llmf_001, llmf_002, ...",
        },
        "framework": {
            "type": "string",
            "description": "Framework label exactly as given in the input routing.",
        },
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "cited_segment_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "segment_id values from the input that ground this finding.",
        },
        "cited_entity_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "entity_id values from the input that ground this finding.",
        },
        "quoted_evidence": {
            "type": "string",
            "description": "Verbatim ad text the finding is about.",
        },
        "claim_candidate_id": {
            "type": ["string", "null"],
            "description": "claim_id from the input, or null if segment-level.",
        },
        "regulation_citations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Citations of the provided regulation excerpts relied on, "
                           "e.g. '12 CFR § 1030.8(b)'.",
        },
        "reasoning": {
            "type": "string",
            "description": "Why the ad text does or does not satisfy the cited rule.",
        },
        "scope_of_improvement": {
            "type": "string",
            "description": "Concrete, actionable edit to the ad that removes or "
                           "reduces the compliance risk (what to change, add, or "
                           "make more prominent).",
        },
    },
    "required": [
        "finding_id", "framework", "severity", "verdict",
        "cited_segment_ids", "cited_entity_ids", "quoted_evidence",
        "claim_candidate_id", "regulation_citations", "reasoning",
        "scope_of_improvement",
    ],
    "additionalProperties": False,
}

LLM_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {"type": "array", "items": _FINDING_SCHEMA},
        "reviewed_clear": {
            "type": "array",
            "items": {"type": "string"},
            "description": "claim_id / segment_id values evaluated and found clear "
                           "(no finding warranted).",
        },
        "frameworks_evaluated": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["findings", "reviewed_clear", "frameworks_evaluated"],
    "additionalProperties": False,
}


class SchemaError(ValueError):
    """LLM output failed structural validation."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def validate_llm_output(payload: Any) -> None:
    """Structural validation matching LLM_OUTPUT_SCHEMA.

    Anthropic structured outputs already guarantee the shape; this exists
    for the OpenRouter path (JSON mode gives valid JSON, not a valid
    shape) and as a belt for both.
    """
    problems: list[str] = []

    def _is_str_list(v: Any) -> bool:
        return isinstance(v, list) and all(isinstance(x, str) for x in v)

    if not isinstance(payload, dict):
        raise SchemaError(["top level is not a JSON object"])

    for key in ("findings", "reviewed_clear", "frameworks_evaluated"):
        if key not in payload:
            problems.append(f"missing key: {key}")
    if problems:
        raise SchemaError(problems)

    if not _is_str_list(payload["reviewed_clear"]):
        problems.append("reviewed_clear must be an array of strings")
    if not _is_str_list(payload["frameworks_evaluated"]):
        problems.append("frameworks_evaluated must be an array of strings")
    if not isinstance(payload["findings"], list):
        problems.append("findings must be an array")
        raise SchemaError(problems)

    for i, f in enumerate(payload["findings"]):
        where = f"findings[{i}]"
        if not isinstance(f, dict):
            problems.append(f"{where} is not an object")
            continue
        for key in _FINDING_SCHEMA["required"]:
            if key not in f:
                problems.append(f"{where} missing key: {key}")
        for key in ("finding_id", "framework", "quoted_evidence",
                    "reasoning", "scope_of_improvement"):
            if key in f and not isinstance(f[key], str):
                problems.append(f"{where}.{key} must be a string")
        if "severity" in f and f["severity"] not in SEVERITIES:
            problems.append(f"{where}.severity must be one of {SEVERITIES}")
        if "verdict" in f and f["verdict"] not in VERDICTS:
            problems.append(f"{where}.verdict must be one of {VERDICTS}")
        for key in ("cited_segment_ids", "cited_entity_ids", "regulation_citations"):
            if key in f and not _is_str_list(f[key]):
                problems.append(f"{where}.{key} must be an array of strings")
        if "claim_candidate_id" in f and not (
            f["claim_candidate_id"] is None or isinstance(f["claim_candidate_id"], str)
        ):
            problems.append(f"{where}.claim_candidate_id must be a string or null")

    if problems:
        raise SchemaError(problems)

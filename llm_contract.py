"""Output contract for the LLM+RAG compliance-review layer.

This is the second input to the deterministic rule engine (the first is
``schema.AssetRepresentation``). The LLM layer judges — verdicts and
severities live HERE, never in the CV/NLP structures — and every
judgment must be traceable: findings cite the segment/entity/claim ids
of the AssetRepresentation they were derived from, so the rule engine
can deterministically verify that citations resolve and evidence quotes
match. Whether those citations actually resolve is checked by the rule
engine against the paired asset, not by this contract.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from schema import Framework

Severity = Literal["critical", "high", "medium", "low"]
Verdict = Literal["violation", "potential_violation", "compliant"]


class LLMFinding(BaseModel):
    """One framework-specific judgment about the asset, with citations."""

    finding_id: str = Field(
        ...,
        min_length=1,
        description="Stable, output-unique identifier for this finding (e.g. 'llmf_001').",
    )
    framework: Framework = Field(
        ...,
        description="Regulatory framework this finding is issued under.",
    )
    severity: Severity = Field(
        ...,
        description="LLM-assessed severity of the issue.",
    )
    verdict: Verdict = Field(
        ...,
        description=(
            "violation: clear breach; potential_violation: needs human or "
            "additional evidence; compliant: reviewed and found acceptable."
        ),
    )
    cited_segment_ids: list[str] = Field(
        default_factory=list,
        description="AssetRepresentation segment ids this finding rests on.",
    )
    cited_entity_ids: list[str] = Field(
        default_factory=list,
        description="AssetRepresentation entity ids this finding rests on.",
    )
    quoted_evidence: Optional[str] = Field(
        default=None,
        description=(
            "Verbatim quote from a cited segment supporting the finding. "
            "The rule engine verifies the quote appears in cited text."
        ),
    )
    claim_candidate_id: Optional[str] = Field(
        default=None,
        description="Id of the ClaimCandidate this finding addresses, if any.",
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        description="LLM's stated rationale, kept for the audit trail.",
    )


class LLMOutput(BaseModel):
    """Complete LLM review of one asset: findings plus coverage record."""

    asset_id: str = Field(
        ...,
        min_length=1,
        description="Id of the reviewed asset; must match the AssetRepresentation.",
    )
    findings: list[LLMFinding] = Field(
        default_factory=list,
        description="All findings, including compliant verdicts. Empty is valid.",
    )
    reviewed_clear: list[str] = Field(
        default_factory=list,
        description=(
            "Ids (claim candidates / segments) the LLM examined and found "
            "unproblematic without issuing a finding — the coverage record "
            "the rule engine checks completeness against."
        ),
    )
    frameworks_evaluated: list[str] = Field(
        default_factory=list,
        description=(
            "Framework values the LLM actually evaluated. The rule engine "
            "compares this against the routing label's frameworks."
        ),
    )
    llm_meta: dict = Field(
        default_factory=dict,
        description=(
            "Provenance of the LLM run (model, prompt version, RAG corpus "
            "hash, timestamps ...). Opaque to the rule engine except for "
            "presence checks."
        ),
    )

    @model_validator(mode="after")
    def _unique_finding_ids(self) -> "LLMOutput":
        ids = [f.finding_id for f in self.findings]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate finding_id in findings")
        return self

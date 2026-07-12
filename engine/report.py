"""The engine's final document: one auditable result for one ad.

``EngineRunResult`` merges what every layer produced:

  * ``llm_review``       — the FINAL LLM review in the product format
                           (sample_output-LLMresponse.json shape, with
                           scope_of_improvement / regulation_citations,
                           verdicts as the LLM wrote them);
  * ``verification``     — the rule engine's last EngineReport (summary):
                           review soundness, asset defects, advisories;
  * ``rounds``           — the full audit trail: every LLM round, the
                           feedback that produced it, and the rule-engine
                           verdict on it;
  * ``human_review``     — set when the loop exhausted its LLM callbacks:
                           what failed and how the operator resumes;
  * ``provenance``       — everything needed to reproduce the verdict
                           (models, prompt/ruleset versions + hashes,
                           OCR backend, corpus fingerprint, timings).

Statuses: ``passed`` (review verified sound), ``human_review`` (operator
interference requested), ``llm_error`` (provider/transport failure —
surfaced, never swallowed).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from . import _paths  # noqa: F401  (sys.path bootstrap - must be first)

Status = Literal["passed", "human_review", "llm_error"]


class RoundAudit(BaseModel):
    """One LLM round zipped with the rule engine's verdict on it."""

    round: int
    was_rule_engine_callback: bool = False
    had_human_guidance: bool = False
    feedback_sent_to_llm: Optional[str] = None
    llm_review: dict = Field(default_factory=dict,
                             description="Original review document this round "
                             "(product format, verdicts unmapped).")
    adapter_notes: list[dict] = Field(default_factory=list)
    rule_engine_passed: Optional[bool] = None
    failed_checks: list[dict] = Field(default_factory=list)


class HumanReviewRequest(BaseModel):
    """Operator interference request after the callback budget ran out."""

    reason: str
    failed_checks: list[dict] = Field(default_factory=list)
    instructions: list[dict] = Field(
        default_factory=list,
        description="Rule-engine fix directives still outstanding - what the "
        "LLM kept getting wrong; the operator prompt should address these.")
    how_to_resume: str


class Verification(BaseModel):
    """Rule-engine outcome on the final round (Layer 4's verdict)."""

    review_passed: bool
    checks_run: int
    failed_checks: list[dict] = Field(default_factory=list)
    asset_defects: list[dict] = Field(
        default_factory=list,
        description="Deterministic true statements about the ad itself "
        "(missing disclosures, prominence floors) - no re-review changes "
        "them; fixing the creative does.")
    advisories: list[dict] = Field(
        default_factory=list,
        description="Applicability flags for advertiser-level obligations; "
        "informational, never gate the verdict.")
    ruleset_version: str = ""
    ruleset_hash: str = ""


class EngineRunResult(BaseModel):
    """Complete outcome of one engine run over one ad asset."""

    run_id: str
    asset_id: str
    tier: str
    status: Status
    llm_rounds_used: int
    max_llm_rounds: int
    llm_review: Optional[dict] = Field(
        default=None,
        description="Final LLM review document (product format). None only "
        "when the very first LLM call failed.")
    verification: Optional[Verification] = None
    rounds: list[RoundAudit] = Field(default_factory=list)
    human_review: Optional[HumanReviewRequest] = None
    llm_error: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    provenance: dict = Field(default_factory=dict)
    timings_ms: dict = Field(default_factory=dict)
    resumed_from_run_id: Optional[str] = None
    asset: Optional[dict] = Field(
        default=None,
        description="The AssetRepresentation reviewed (included on request).")

    def summary_lines(self) -> list[str]:
        """Human-readable console summary (ASCII only)."""
        lines = [
            f"run {self.run_id}  asset {self.asset_id}",
            f"tier {self.tier}  status {self.status.upper()}  "
            f"llm rounds {self.llm_rounds_used}/{self.max_llm_rounds}",
        ]
        if self.llm_review:
            findings = self.llm_review.get("findings", [])
            by_verdict: dict[str, int] = {}
            for f in findings:
                by_verdict[f.get("verdict", "?")] = by_verdict.get(f.get("verdict", "?"), 0) + 1
            verdicts = ", ".join(f"{k}={v}" for k, v in sorted(by_verdict.items())) or "none"
            lines.append(f"llm findings: {len(findings)} ({verdicts}); "
                         f"model {self.llm_review.get('llm_meta', {}).get('model', '?')}")
            for f in findings:
                lines.append(
                    f"  - [{f.get('severity', '?'):6s}] {f.get('framework', '?')}"
                    f" {f.get('verdict', '?')}: "
                    f"{(f.get('quoted_evidence') or f.get('reasoning') or '')[:90]}")
        if self.verification:
            v = self.verification
            lines.append(
                f"rule engine: {'SOUND' if v.review_passed else 'NOT SOUND'} "
                f"({v.checks_run} checks, {len(v.failed_checks)} review failures, "
                f"{len(v.asset_defects)} asset defects, "
                f"{len(v.advisories)} advisories)")
            for d in v.asset_defects:
                lines.append(f"  ~ asset defect [{d.get('severity', '?')}] "
                             f"{d.get('check_id', '?')}: {d.get('message', '')[:100]}")
        if self.human_review:
            lines.append("HUMAN REVIEW REQUESTED:")
            lines.append(f"  reason: {self.human_review.reason}")
            for ins in self.human_review.instructions:
                lines.append(f"  * {ins.get('check_id', '?')}: "
                             f"{ins.get('instruction', '')[:120]}")
            lines.append(f"  resume: {self.human_review.how_to_resume}")
        if self.llm_error:
            lines.append(f"LLM ERROR: {self.llm_error}")
        for w in self.warnings:
            lines.append(f"warning: {w}")
        return lines

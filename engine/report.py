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

import textwrap
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from . import _paths  # noqa: F401  (sys.path bootstrap - must be first)

Status = Literal["passed", "human_review", "llm_error"]

#: Verdicts meaning "this framework did NOT come back clean".  The rule
#: engine's own definition of an adverse finding is violation /
#: potential_violation (llm_integration_guide.md S4); the product format
#: additionally uses ``needs_review``, which engine/adapter.py maps onto
#: potential_violation before the checks run - so it counts as adverse here
#: too.  Anything else (``compliant``) leaves the framework clear.
ADVERSE_VERDICTS = frozenset({"violation", "potential_violation", "needs_review"})

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _worst_severity(severities: list[str]) -> Optional[str]:
    ranked = sorted(severities, key=lambda s: _SEVERITY_RANK.get(s, 99))
    return ranked[0] if ranked else None


def _field_block(label: str, text: str, width: int = 72) -> list[str]:
    """One wrapped ``label: text`` block with aligned continuation lines."""
    body = " ".join(str(text).split())
    wrapped = textwrap.wrap(body, width=width) or [""]
    out = [f"     {label:<8}: {wrapped[0]}"]
    out.extend(f"               {w}" for w in wrapped[1:])
    return out


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

    def adverse_findings(self) -> list[dict]:
        """Final-round findings that carry legal exposure, worst first.

        Only the FINAL review is consulted - ``rounds`` keeps the earlier
        ones for the audit trail, but a finding the retry loop corrected
        away is not something to show the advertiser.
        """
        findings = [
            f for f in (self.llm_review or {}).get("findings", [])
            if str(f.get("verdict", "")).lower() in ADVERSE_VERDICTS
        ]
        return sorted(findings, key=lambda f: _SEVERITY_RANK.get(
            str(f.get("severity", "")).lower(), 99))

    def framework_status(self) -> list[dict[str, Any]]:
        """Per-framework PASSED / FAILED roll-up.

        The work order is the LLM's own ``frameworks_evaluated`` (the list
        ALL-COV-001 grades it against) plus any framework the org's plan
        removed before the review ran.  A framework FAILED when the final
        round left an adverse finding against it, PASSED when it was
        evaluated and nothing adverse remains, and NOT_REVIEWED when the
        plan excluded it (the advertiser is told, not left guessing).
        """
        review = self.llm_review or {}
        evaluated = [str(f) for f in review.get("frameworks_evaluated", [])]
        dropped = [str(f) for f in (self.provenance.get("saas") or {}).get(
            "frameworks_dropped_by_plan", [])]

        hits: dict[str, list[str]] = {}
        for f in self.adverse_findings():
            hits.setdefault(str(f.get("framework", "?")), []).append(
                str(f.get("severity", "")).lower())

        rows: list[dict[str, Any]] = []
        for fw in dict.fromkeys(evaluated):          # order-preserving dedupe
            sev = hits.get(fw, [])
            rows.append({"framework": fw,
                         "status": "failed" if sev else "passed",
                         "findings": len(sev),
                         "worst_severity": _worst_severity(sev)})
        # A finding may only name a framework outside frameworks_evaluated if
        # ALL-CON-005 did not hold that round - surface it, never silently drop.
        seen = {r["framework"] for r in rows}
        for fw, sev in hits.items():
            if fw not in seen:
                rows.append({"framework": fw, "status": "failed",
                             "findings": len(sev),
                             "worst_severity": _worst_severity(sev)})
        for fw in dict.fromkeys(dropped):
            rows.append({"framework": fw, "status": "not_reviewed",
                         "findings": 0, "worst_severity": None})
        return rows

    def summary_lines(self) -> list[str]:
        """Human-readable console summary (ASCII only).

        Ordered the way a reviewer reads it: which regulation frameworks the
        ad was graded against and how each came out, THEN the findings that
        may create legal exposure.  Run ``status`` is deliberately not the
        headline - it says whether the REVIEW is sound, not whether the AD
        is clean (llm_integration_guide.md S2).
        """
        lines = [
            f"run {self.run_id}  asset {self.asset_id}",
            f"tier {self.tier}  review {self.status.upper()}  "
            f"llm rounds {self.llm_rounds_used}/{self.max_llm_rounds}"
            + (f"  model {self.llm_review.get('llm_meta', {}).get('model', '?')}"
               if self.llm_review else ""),
        ]

        rows = self.framework_status()
        if rows:
            failed = [r for r in rows if r["status"] == "failed"]
            passed = [r for r in rows if r["status"] == "passed"]
            skipped = [r for r in rows if r["status"] == "not_reviewed"]
            lines.append("")
            lines.append("REGULATION FRAMEWORKS APPLIED TO THIS AD"
                         f"  (passed {len(passed)}, failed {len(failed)}"
                         + (f", not reviewed {len(skipped)}" if skipped else "")
                         + ")")
            for r in sorted(failed, key=lambda r: _SEVERITY_RANK.get(
                    r["worst_severity"] or "", 99)):
                lines.append(
                    f"  FAILED        {str(r['framework']):<12} "
                    f"{r['findings']} finding(s), worst severity "
                    f"{str(r['worst_severity'] or '?').upper()}")
            for r in passed:
                lines.append(f"  PASSED        {str(r['framework']):<12} "
                             "no issues found")
            for r in skipped:
                lines.append(f"  NOT REVIEWED  {str(r['framework']):<12} "
                             f"not included in the {self.tier} plan")

        adverse = self.adverse_findings()
        if adverse:
            lines.append("")
            lines.append(f"FINDINGS THAT MAY CAUSE LEGAL ISSUES ({len(adverse)})")
            for i, f in enumerate(adverse, 1):
                lines.append("")
                lines.append(
                    f"  {i}. [{str(f.get('severity', '?')).upper()}] "
                    f"{f.get('framework', '?')} - "
                    f"{str(f.get('verdict', '?')).replace('_', ' ')}")
                if f.get("quoted_evidence"):
                    lines.extend(_field_block(
                        "ad copy", f'"{f["quoted_evidence"]}"'))
                if f.get("regulation_citations"):
                    lines.extend(_field_block("rule", ", ".join(
                        str(c) for c in f["regulation_citations"])))
                if f.get("reasoning"):
                    lines.extend(_field_block("issue", f["reasoning"]))
                if f.get("scope_of_improvement"):
                    lines.extend(_field_block("fix", f["scope_of_improvement"]))

        if self.verification:
            v = self.verification
            if v.asset_defects:
                lines.append("")
                lines.append(f"CREATIVE DEFECTS ({len(v.asset_defects)}) - "
                             "fix the ad itself; re-reviewing will not clear these")
                for d in v.asset_defects:
                    lines.append(
                        f"  - [{str(d.get('severity', '?')).upper()}] "
                        f"{d.get('check_id', '?')}: {d.get('message', '')}")
            lines.append("")
            lines.append(
                f"review verification: {'SOUND' if v.review_passed else 'NOT SOUND'} "
                f"({v.checks_run} checks, {len(v.failed_checks)} review failures, "
                f"{len(v.advisories)} advisories)")

        if self.human_review:
            lines.append("")
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

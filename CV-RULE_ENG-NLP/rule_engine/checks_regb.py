"""ECOA / Reg B checks — §5 of docs/check_taxonomy.md (12 CFR Part 1002).

The mechanizable slice is narrow and honest: make sure prohibited-basis
vocabulary in a credit ad was at least looked at. The router now emits
ECOA for credit-extension products (2026-07-10 change), so REGB-COV-001
can genuinely trigger; the remaining checks still register universally
("*") and gate on their own trigger conditions rather than on routing.
One function per check_id; docstring = taxonomy row.
"""

from __future__ import annotations

from rule_engine.core import CheckContext, CheckResult, register_check
from rule_engine.lexicons import (
    CREDIT_PRODUCTS,
    LEXICON_VERSION,
    covered_ids,
    entities_of_type,
    match_lexicon,
    segments_matching,
)


@register_check("REGB-COV-001", families=["coverage"], frameworks=["*"])
def regb_cov_001_ecoa_evaluated(ctx: CheckContext) -> CheckResult:
    """REGB-COV-001 (coverage, ECOA, high).
    Trigger: "ECOA" in A.routing.frameworks (now emitted for credit-
    extension products).
    Fail: "ECOA" not in L.frameworks_evaluated.
    Evidence: routing.frameworks, frameworks_evaluated.
    """
    if "ECOA" not in ctx.routed_frameworks:
        return CheckResult(
            check_id="REGB-COV-001", passed=True, severity="high",
            message="not triggered: ECOA not routed",
            evidence={"triggered": False},
        )
    ok = "ECOA" in ctx.llm.frameworks_evaluated
    return CheckResult(
        check_id="REGB-COV-001", passed=ok, severity="high",
        message="ECOA was evaluated" if ok
        else "asset routes to ECOA but the LLM never evaluated it",
        evidence={"routed": sorted(ctx.routed_frameworks),
                  "frameworks_evaluated": ctx.llm.frameworks_evaluated},
    )


@register_check("REGB-COV-002", families=["coverage"], frameworks=["*"])
def regb_cov_002_prohibited_basis_reviewed(ctx: CheckContext) -> CheckResult:
    """REGB-COV-002 (coverage, ECOA, medium).
    Trigger: CREDIT AND LEX:PROHIBITED_BASIS matches segment S.
    Fail: S not covered — prohibited-basis vocabulary in a credit ad that
    no finding cites and reviewed_clear doesn't list.
    Evidence: S id, matched lexeme + span.
    """
    if ctx.asset.routing.product_type.value not in CREDIT_PRODUCTS:
        return CheckResult(
            check_id="REGB-COV-002", passed=True, severity="medium",
            message="not triggered: not a credit product",
            evidence={"triggered": False},
        )
    hits = segments_matching(ctx, "PROHIBITED_BASIS")
    if not hits:
        return CheckResult(
            check_id="REGB-COV-002", passed=True, severity="medium",
            message="not triggered: no prohibited-basis vocabulary",
            evidence={"triggered": False},
        )
    covered = covered_ids(ctx.llm)
    unreviewed = [{"segment_id": s.segment_id, "matches": m, "text": s.text}
                  for s, m in hits if s.segment_id not in covered]
    if unreviewed:
        return CheckResult(
            check_id="REGB-COV-002", passed=False, severity="medium",
            message="prohibited-basis vocabulary in a credit ad was "
                    "reviewed by nobody",
            evidence={"unreviewed_segments": unreviewed,
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="REGB-COV-002", passed=True, severity="medium",
        message="prohibited-basis vocabulary was reviewed",
        evidence={"segments_checked": [s.segment_id for s, _ in hits]},
    )


@register_check("REGB-CON-001", families=["consistency"], frameworks=["*"])
def regb_con_001_ecoa_finding_needs_credit_signals(ctx: CheckContext) -> CheckResult:
    """REGB-CON-001 (consistency, ECOA, low).
    Trigger: any finding with framework = ECOA.
    Fail: NOT CREDIT AND zero credit-signal entities (apr, rate, fee) —
    ECOA finding on an asset with no credit signals (advisory: likely
    misfiled).
    Evidence: finding_id, product_type, entity-type census.
    """
    ecoa_findings = ctx.findings_by_framework.get("ECOA", [])
    if not ecoa_findings:
        return CheckResult(
            check_id="REGB-CON-001", passed=True, severity="low",
            message="not triggered: no ECOA findings",
            evidence={"triggered": False},
        )
    product = ctx.asset.routing.product_type.value
    signals = entities_of_type(ctx, "apr", "rate", "fee")
    if product not in CREDIT_PRODUCTS and not signals:
        census: dict[str, int] = {}
        for e in ctx.asset.entities:
            census[e.entity_type.value] = census.get(e.entity_type.value, 0) + 1
        return CheckResult(
            check_id="REGB-CON-001", passed=False, severity="low",
            message="ECOA findings on an asset with no credit signals "
                    "(likely misfiled framework)",
            evidence={"finding_ids": [f.finding_id for f in ecoa_findings],
                      "product_type": product,
                      "entity_type_census": census},
        )
    return CheckResult(
        check_id="REGB-CON-001", passed=True, severity="low",
        message="ECOA findings are backed by credit signals",
        evidence={"product_type": product,
                  "credit_signal_entities": [e.entity_id for e in signals]},
    )


@register_check("REGB-SEV-001", families=["severity_sanity"], frameworks=["*"])
def regb_sev_001_prohibited_basis_floor(ctx: CheckContext) -> CheckResult:
    """REGB-SEV-001 (severity_sanity, ECOA, low).
    Trigger: ECOA finding with verdict = violation whose cited segments
    match LEX:PROHIBITED_BASIS.
    Fail: severity = low — an affirmed prohibited-basis violation floors
    at medium.
    Evidence: finding_id, severity, matched lexeme.
    """
    underrated = []
    for f in ctx.findings_by_framework.get("ECOA", []):
        if f.verdict != "violation" or f.severity != "low":
            continue
        matched = []
        for sid in f.cited_segment_ids:
            seg = ctx.segment_by_id.get(sid)
            if seg:
                matched += match_lexicon("PROHIBITED_BASIS", seg.text)
        if matched:
            underrated.append({"finding_id": f.finding_id,
                               "severity": f.severity,
                               "matched_lexemes": sorted(set(matched))})
    if underrated:
        return CheckResult(
            check_id="REGB-SEV-001", passed=False, severity="low",
            message="affirmed prohibited-basis violations rated low",
            evidence={"underrated_findings": underrated,
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="REGB-SEV-001", passed=True, severity="low",
        message="no underrated prohibited-basis violations",
        evidence={"ecoa_findings_checked":
                  len(ctx.findings_by_framework.get("ECOA", []))},
    )

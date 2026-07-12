"""FDIC Part 328 checks — §4 of docs/check_taxonomy.md (12 CFR Part 328).

Deliberately separate from Reg DD: Part 328 governs WHO may claim FDIC
insurance and HOW; Reg DD governs deposit terms. schema.Framework.FDIC
now exists (added in the 2026-07-10 bump), so findings can be filed under
Part 328. These checks still register universally ("*") and key
exclusively on LEX:FDIC matches in the asset plus the coverage record,
never on product routing — insured-status wording ("Member FDIC") appears
on brand ads, hybrid ads, and misrepresentations alike, so wording-keyed
triggering is intentional and broader than any single routed framework.
One function per check_id; docstring = taxonomy row.
"""

from __future__ import annotations

from rule_engine.core import CheckContext, CheckResult, register_check
from rule_engine.lexicons import (
    LEXICON_VERSION,
    UNINSURABLE_PRODUCTS,
    segments_matching,
)


def _fdic_segments(ctx: CheckContext):
    return segments_matching(ctx, "FDIC")


@register_check("FDIC328-STR-001", families=["structural"], frameworks=["*"],
                scope="asset")
def fdic328_str_001_uninsurable_product(ctx: CheckContext) -> CheckResult:
    """FDIC328-STR-001 (structural, Part 328, critical).
    Trigger: LEX:FDIC matches any segment.
    Fail: A.routing.product_type in {investment, crypto, insurance} —
    insured-status wording on an uninsurable product class (§328.102(b):
    misrepresentation; the classic neobank/crypto failure).
    Evidence: matching segment_id + matched span + text, product_type,
    routing.signal.
    """
    hits = _fdic_segments(ctx)
    if not hits:
        return CheckResult(
            check_id="FDIC328-STR-001", passed=True, severity="critical",
            message="not triggered: no insured-status wording",
            evidence={"triggered": False},
        )
    product = ctx.asset.routing.product_type.value
    if product in UNINSURABLE_PRODUCTS:
        return CheckResult(
            check_id="FDIC328-STR-001", passed=False, severity="critical",
            message="FDIC insured-status wording on an uninsurable "
                    "product class",
            evidence={"fdic_segments": [
                          {"segment_id": s.segment_id, "matches": m,
                           "text": s.text} for s, m in hits],
                      "product_type": product,
                      "routing_signal": ctx.asset.routing.signal,
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="FDIC328-STR-001", passed=True, severity="critical",
        message="insured-status wording on an insurable product class",
        evidence={"fdic_segments": [s.segment_id for s, _ in hits],
                  "product_type": product},
    )


@register_check("FDIC328-STR-002", families=["structural"], frameworks=["*"],
                scope="asset")
def fdic328_str_002_hybrid_needs_disclaimer(ctx: CheckContext) -> CheckResult:
    """FDIC328-STR-002 (structural, Part 328, medium).
    Trigger: LEX:FDIC matches AND LEX:INVESTMENT matches somewhere in the
    asset (hybrid ad: insured deposit claim + non-deposit product content).
    Fail: no segment matches LEX:NON_DEPOSIT_DISCLAIMER ("not
    FDIC-insured / may lose value / not bank guaranteed" family,
    §328.102(b)(5)).
    Evidence: FDIC segment_id, investment-lexicon segment_id, statement
    that no disclaimer lexeme found.
    """
    fdic_hits = _fdic_segments(ctx)
    invest_hits = segments_matching(ctx, "INVESTMENT")
    if not fdic_hits or not invest_hits:
        return CheckResult(
            check_id="FDIC328-STR-002", passed=True, severity="medium",
            message="not triggered: not a hybrid insured/non-deposit ad",
            evidence={"triggered": False},
        )
    disclaimer_hits = segments_matching(ctx, "NON_DEPOSIT_DISCLAIMER")
    if not disclaimer_hits:
        return CheckResult(
            check_id="FDIC328-STR-002", passed=False, severity="medium",
            message="hybrid insured/non-deposit ad without the non-deposit "
                    "disclaimer",
            evidence={"fdic_segments": [
                          {"segment_id": s.segment_id, "matches": m}
                          for s, m in fdic_hits],
                      "investment_segments": [
                          {"segment_id": s.segment_id, "matches": m}
                          for s, m in invest_hits],
                      "disclaimer_lexicon_hits": 0,
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="FDIC328-STR-002", passed=True, severity="medium",
        message="hybrid ad carries a non-deposit disclaimer",
        evidence={"disclaimer_segments":
                  [s.segment_id for s, _ in disclaimer_hits]},
    )


@register_check("FDIC328-COV-001", families=["coverage"], frameworks=["*"])
def fdic328_cov_001_insured_claims_reviewed(ctx: CheckContext) -> CheckResult:
    """FDIC328-COV-001 (coverage, Part 328, high).
    Trigger: LEX:FDIC matches segment S.
    Fail: S not covered — an insured-status claim no finding cites and
    reviewed_clear doesn't list; insured-status wording must never pass
    unreviewed.
    Evidence: S id, matched span + text.
    """
    hits = _fdic_segments(ctx)
    if not hits:
        return CheckResult(
            check_id="FDIC328-COV-001", passed=True, severity="high",
            message="not triggered: no insured-status wording",
            evidence={"triggered": False},
        )
    cited = set(ctx.llm.reviewed_clear)
    for f in ctx.llm.findings:
        cited.update(f.cited_segment_ids)
    unreviewed = [{"segment_id": s.segment_id, "matches": m, "text": s.text}
                  for s, m in hits if s.segment_id not in cited]
    if unreviewed:
        return CheckResult(
            check_id="FDIC328-COV-001", passed=False, severity="high",
            message="insured-status wording passed unreviewed",
            evidence={"unreviewed_segments": unreviewed,
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="FDIC328-COV-001", passed=True, severity="high",
        message="every insured-status segment was reviewed",
        evidence={"fdic_segments": [s.segment_id for s, _ in hits]},
    )


@register_check("FDIC328-CON-001", families=["consistency"], frameworks=["*"])
def fdic328_con_001_regdd_only_treatment(ctx: CheckContext) -> CheckResult:
    """FDIC328-CON-001 (consistency, Part 328, low).
    Trigger: LEX:FDIC matches segment S AND >=1 finding cites S.
    Fail: every finding citing S has framework = Reg_DD — insured-status
    treated purely as a deposit-terms issue (mirror of REGDD-CON-001;
    now that Framework.FDIC exists, findings on insured-status wording
    should cite FDIC — or at least CFPB/FTC — not Reg_DD alone).
    Evidence: finding ids + frameworks, S id.
    """
    hits = _fdic_segments(ctx)
    conflated = []
    for s, m in hits:
        citing = [f for f in ctx.llm.findings
                  if s.segment_id in f.cited_segment_ids]
        if citing and all(f.framework.value == "Reg_DD" for f in citing):
            conflated.append({
                "segment_id": s.segment_id, "matches": m,
                "citing_findings": [
                    {"finding_id": f.finding_id,
                     "framework": f.framework.value} for f in citing],
            })
    if conflated:
        return CheckResult(
            check_id="FDIC328-CON-001", passed=False, severity="low",
            message="insured-status wording treated purely as a Reg DD "
                    "deposit-terms issue",
            evidence={"conflated_segments": conflated,
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="FDIC328-CON-001", passed=True, severity="low",
        message="no Reg-DD-only treatment of insured-status wording"
        if hits else "not triggered: no insured-status wording",
        evidence={"fdic_segments_cited": sum(
            1 for s, _ in hits
            if any(s.segment_id in f.cited_segment_ids
                   for f in ctx.llm.findings))} if hits
        else {"triggered": False},
    )


@register_check("FDIC328-SEV-001", families=["severity_sanity"], frameworks=["*"])
def fdic328_sev_001_misrep_floor(ctx: CheckContext) -> CheckResult:
    """FDIC328-SEV-001 (severity_sanity, Part 328, high).
    Trigger: a finding cites an LEX:FDIC-matching segment with verdict =
    violation while product_type in {investment, crypto, insurance}.
    Fail: severity in {medium, low} — misrepresenting deposit insurance
    on uninsurable products has a floor of high.
    Evidence: finding_id, severity, FDIC328-STR-001 evidence.
    """
    product = ctx.asset.routing.product_type.value
    fdic_seg_ids = {s.segment_id for s, _ in _fdic_segments(ctx)}
    if product not in UNINSURABLE_PRODUCTS or not fdic_seg_ids:
        return CheckResult(
            check_id="FDIC328-SEV-001", passed=True, severity="high",
            message="not triggered: no insured-status violation exposure",
            evidence={"triggered": False},
        )
    underrated = [
        {"finding_id": f.finding_id, "severity": f.severity,
         "cited_fdic_segments": sorted(fdic_seg_ids & set(f.cited_segment_ids))}
        for f in ctx.llm.findings
        if f.verdict == "violation" and f.severity in ("medium", "low")
        and fdic_seg_ids & set(f.cited_segment_ids)
    ]
    if underrated:
        return CheckResult(
            check_id="FDIC328-SEV-001", passed=False, severity="high",
            message="insured-status misrepresentation on an uninsurable "
                    "product rated below high",
            evidence={"underrated_findings": underrated,
                      "product_type": product},
        )
    return CheckResult(
        check_id="FDIC328-SEV-001", passed=True, severity="high",
        message="no underrated insured-status violations",
        evidence={"product_type": product,
                  "fdic_segments": sorted(fdic_seg_ids)},
    )

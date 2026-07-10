"""FTC Act §5 checks — §1 of docs/check_taxonomy.md (15 U.S.C. § 45).

The engine cannot decide deception; it decides that the FTC baseline was
evaluated, that substantiation-burden claim types were each looked at,
and that absolute claims were not left standing with no qualifying text.
One function per check_id; docstring = taxonomy row.
"""

from __future__ import annotations

from rule_engine.core import CheckContext, CheckResult, register_check
from rule_engine.lexicons import (
    CREDIT_PRODUCTS,
    HEIGHT_MIN_PCT,
    LEXICON_VERSION,
    PROX_MAX,
    THRESHOLDS_VERSION,
    covered_ids,
    entities_of_type,
    entity_evidence,
    heights_by_segment,
    proximity_findings,
    segments_matching,
)

_SUBSTANTIATION_TYPES = ("performance", "comparative", "guarantee", "risk_free")
_DISCLOSURE_ROLES = ("disclosure", "fine_print", "legal")


@register_check("FTC5-COV-001", families=["coverage"], frameworks=["FTC"])
def ftc5_cov_001_baseline_evaluated(ctx: CheckContext) -> CheckResult:
    """FTC5-COV-001 (coverage, FTC, high).
    Trigger: "FTC" in A.routing.frameworks (always true under current router).
    Fail: "FTC" not in L.frameworks_evaluated.
    Evidence: routing.frameworks, frameworks_evaluated.
    """
    ok = "FTC" in ctx.llm.frameworks_evaluated
    return CheckResult(
        check_id="FTC5-COV-001", passed=ok, severity="high",
        message="FTC baseline was evaluated" if ok
        else "asset routes to FTC but the LLM never evaluated it",
        evidence={"routed": sorted(ctx.routed_frameworks),
                  "frameworks_evaluated": ctx.llm.frameworks_evaluated},
    )


@register_check("FTC5-COV-002", families=["coverage"], frameworks=["FTC"])
def ftc5_cov_002_substantiation_claims_reviewed(ctx: CheckContext) -> CheckResult:
    """FTC5-COV-002 (coverage, FTC, high).
    Trigger: claim candidates with claim_type in {performance, comparative,
    guarantee, risk_free} exist (substantiation-burden types).
    Fail: any such claim_id not covered — strict subset of ALL-COV-002,
    kept so the failure is attributed to the §5 substantiation duty.
    Evidence: uncovered claim ids + type + text.
    """
    burdened = [c for c in ctx.asset.claim_candidates
                if c.claim_type.value in _SUBSTANTIATION_TYPES]
    if not burdened:
        return CheckResult(
            check_id="FTC5-COV-002", passed=True, severity="high",
            message="not triggered: no substantiation-burden claims",
            evidence={"triggered": False},
        )
    uncovered = [
        {"claim_id": c.claim_id, "claim_type": c.claim_type.value,
         "text": c.text, "segment_id": c.segment_id}
        for c in burdened if c.claim_id not in ctx.addressed_claim_ids
    ]
    if uncovered:
        return CheckResult(
            check_id="FTC5-COV-002", passed=False, severity="high",
            message="substantiation-burden claims were never reviewed",
            evidence={"unreviewed_claims": uncovered,
                      "unreviewed_claim_ids": [c["claim_id"] for c in uncovered]},
        )
    return CheckResult(
        check_id="FTC5-COV-002", passed=True, severity="high",
        message="every substantiation-burden claim was reviewed",
        evidence={"claims_checked": len(burdened)},
    )


@register_check("FTC5-COV-003", families=["coverage"], frameworks=["FTC"])
def ftc5_cov_003_guaranteed_approval_reviewed(ctx: CheckContext) -> CheckResult:
    """FTC5-COV-003 (coverage, FTC, high).
    Trigger: CREDIT and (entity guarantee_term present OR
    LEX:GUARANTEED_APPROVAL matches a segment).
    Fail: the matching segment/entity not covered — "guaranteed approval"
    language reviewed by nobody.
    Evidence: segment_id, matched lexeme / entity_id, raw_text.
    """
    if ctx.asset.routing.product_type.value not in CREDIT_PRODUCTS:
        return CheckResult(
            check_id="FTC5-COV-003", passed=True, severity="high",
            message="not triggered: not a credit product",
            evidence={"triggered": False},
        )
    guarantee_ents = entities_of_type(ctx, "guarantee_term")
    lex_hits = segments_matching(ctx, "GUARANTEED_APPROVAL")
    if not guarantee_ents and not lex_hits:
        return CheckResult(
            check_id="FTC5-COV-003", passed=True, severity="high",
            message="not triggered: no guaranteed-approval language",
            evidence={"triggered": False},
        )
    covered = covered_ids(ctx.llm)
    unreviewed_ents = [e for e in guarantee_ents
                       if e.entity_id not in covered
                       and e.segment_id not in covered]
    unreviewed_segs = [{"segment_id": s.segment_id, "matches": m}
                       for s, m in lex_hits if s.segment_id not in covered]
    if unreviewed_ents or unreviewed_segs:
        return CheckResult(
            check_id="FTC5-COV-003", passed=False, severity="high",
            message="guaranteed-approval language in a credit ad was "
                    "reviewed by nobody",
            evidence={"unreviewed_entities": entity_evidence(unreviewed_ents),
                      "unreviewed_segments": unreviewed_segs,
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="FTC5-COV-003", passed=True, severity="high",
        message="guaranteed-approval language was reviewed",
        evidence={"entities": len(guarantee_ents), "segments": len(lex_hits)},
    )


@register_check("FTC5-STR-001", families=["structural"], frameworks=["FTC"],
                scope="asset")
def ftc5_str_001_absolute_claims_need_qualifier(ctx: CheckContext) -> CheckResult:
    """FTC5-STR-001 (structural, FTC, medium).
    Trigger: entity superlative or guarantee_term present, OR claim
    guarantee/risk_free present.
    Fail: zero segments with role in {disclosure, fine_print, legal} in
    the whole asset.
    Evidence: triggering entity/claim ids, census of segment roles.
    """
    trigger_ents = entities_of_type(ctx, "superlative", "guarantee_term")
    trigger_claims = [c for c in ctx.asset.claim_candidates
                      if c.claim_type.value in ("guarantee", "risk_free")]
    if not trigger_ents and not trigger_claims:
        return CheckResult(
            check_id="FTC5-STR-001", passed=True, severity="medium",
            message="not triggered: no absolute-claim language",
            evidence={"triggered": False},
        )
    roles = {}
    for s in ctx.asset.segments:
        roles[s.role.value] = roles.get(s.role.value, 0) + 1
    has_qualifier = any(roles.get(r, 0) for r in _DISCLOSURE_ROLES)
    if not has_qualifier:
        return CheckResult(
            check_id="FTC5-STR-001", passed=False, severity="medium",
            message="absolute claims with no disclosure/fine-print/legal "
                    "segment anywhere in the asset",
            evidence={"trigger_entities": entity_evidence(trigger_ents),
                      "trigger_claim_ids": [c.claim_id for c in trigger_claims],
                      "segment_role_census": roles},
        )
    return CheckResult(
        check_id="FTC5-STR-001", passed=True, severity="medium",
        message="qualifying text exists for absolute-claim language",
        evidence={"segment_role_census": roles},
    )


@register_check("FTC5-STR-002", families=["structural"], frameworks=["FTC"],
                scope="asset")
def ftc5_str_002_disclosure_prominence_floor(ctx: CheckContext) -> CheckResult:
    """FTC5-STR-002 (structural, FTC, medium).
    Trigger: a claim candidate's segment has a bbox AND >=1 disclosure-role
    segment has a bbox (so disclosure_proximity / text_height_percent
    findings exist).
    Fail: min disclosure_proximity from the claim segment > PROX_MAX, OR
    the nearest disclosure's text_height_percent < HEIGHT_MIN_PCT.
    Evidence: cv finding_ids, measured values, threshold name+version.
    """
    claim_segs = {c.segment_id for c in ctx.asset.claim_candidates}
    disclosure_segs = {s.segment_id for s in ctx.asset.segments
                       if s.role.value in _DISCLOSURE_ROLES}
    heights = heights_by_segment(ctx)
    nearest: dict[str, object] = {}
    for f in proximity_findings(ctx):
        if f.segment_id in claim_segs and f.related_segment_id in disclosure_segs:
            if f.segment_id not in nearest or f.value < nearest[f.segment_id].value:
                nearest[f.segment_id] = f
    if not nearest:
        return CheckResult(
            check_id="FTC5-STR-002", passed=True, severity="medium",
            message="not triggered: no claim->disclosure proximity "
                    "measurements available",
            evidence={"triggered": False},
        )
    violations = []
    for claim_seg, f in sorted(nearest.items()):
        v = {"claim_segment_id": claim_seg,
             "disclosure_segment_id": f.related_segment_id,
             "proximity_finding_id": f.finding_id, "proximity": f.value}
        h = heights.get(f.related_segment_id)
        if h is not None:
            v["disclosure_height_percent"] = h
        if f.value > PROX_MAX or (h is not None and h < HEIGHT_MIN_PCT):
            violations.append(v)
    if violations:
        return CheckResult(
            check_id="FTC5-STR-002", passed=False, severity="medium",
            message="nearest disclosure fails the prominence floor "
                    "(too far from the claim or too small)",
            evidence={"violations": violations,
                      "thresholds": {"PROX_MAX": PROX_MAX,
                                     "HEIGHT_MIN_PCT": HEIGHT_MIN_PCT},
                      "thresholds_version": THRESHOLDS_VERSION},
        )
    return CheckResult(
        check_id="FTC5-STR-002", passed=True, severity="medium",
        message="every measured claim has a near, legible disclosure",
        evidence={"claim_segments_measured": sorted(nearest),
                  "thresholds_version": THRESHOLDS_VERSION},
    )


@register_check("FTC5-SEV-001", families=["severity_sanity"], frameworks=["FTC"])
def ftc5_sev_001_guarantee_violation_floor(ctx: CheckContext) -> CheckResult:
    """FTC5-SEV-001 (severity_sanity, FTC, medium).
    Trigger: adverse FTC finding whose claim_candidate_id resolves to a
    claim with claim_type in {guarantee, risk_free} and verdict = violation.
    Fail: severity = low.
    Evidence: finding_id, claim_type, severity.
    """
    underrated = []
    for f in ctx.findings_by_framework.get("FTC", []):
        if f.verdict != "violation" or not f.claim_candidate_id:
            continue
        claim = ctx.claim_by_id.get(f.claim_candidate_id)
        if claim and claim.claim_type.value in ("guarantee", "risk_free") \
                and f.severity == "low":
            underrated.append({"finding_id": f.finding_id,
                               "claim_id": claim.claim_id,
                               "claim_type": claim.claim_type.value,
                               "severity": f.severity})
    if underrated:
        return CheckResult(
            check_id="FTC5-SEV-001", passed=False, severity="medium",
            message="affirmed guarantee/risk-free violations rated low",
            evidence={"underrated_findings": underrated},
        )
    return CheckResult(
        check_id="FTC5-SEV-001", passed=True, severity="medium",
        message="no underrated guarantee/risk-free violations",
        evidence={"ftc_findings_checked":
                  len(ctx.findings_by_framework.get("FTC", []))},
    )

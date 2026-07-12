"""Reg DD / TISA checks — §3 of docs/check_taxonomy.md (12 CFR 1030.8).

Boundary note: Reg DD governs deposit-account advertising TERMS (APY,
"free" claims, bonuses) — never insured-status wording, which is FDIC
Part 328 territory (checks_fdic328). Every trigger here keys on deposit
product type plus rate/fee/bonus structure; REGDD-CON-001 polices the
boundary and runs universally since a misfiled Reg_DD finding may sit on
an asset Reg DD was never routed to.
One function per check_id; docstring = taxonomy row.
"""

from __future__ import annotations

from rule_engine.core import CheckContext, CheckResult, register_check
from rule_engine.lexicons import (
    LEXICON_VERSION,
    covered_ids,
    entities_of_type,
    entity_evidence,
    match_lexicon,
    segments_matching,
)


def _is_deposit(ctx: CheckContext) -> bool:
    return ctx.asset.routing.product_type.value == "deposit_account"


@register_check("REGDD-COV-001", families=["coverage"], frameworks=["Reg_DD"])
def regdd_cov_001_regdd_evaluated(ctx: CheckContext) -> CheckResult:
    """REGDD-COV-001 (coverage, Reg_DD, high).
    Trigger: "Reg_DD" in A.routing.frameworks.
    Fail: "Reg_DD" not in L.frameworks_evaluated.
    Evidence: routing.frameworks, frameworks_evaluated.
    """
    ok = "Reg_DD" in ctx.llm.frameworks_evaluated
    return CheckResult(
        check_id="REGDD-COV-001", passed=ok, severity="high",
        message="Reg DD was evaluated" if ok
        else "asset routes to Reg DD but the LLM never evaluated it",
        evidence={"routed": sorted(ctx.routed_frameworks),
                  "frameworks_evaluated": ctx.llm.frameworks_evaluated},
    )


@register_check("REGDD-STR-001", families=["structural"], frameworks=["Reg_DD"],
                scope="asset")
def regdd_str_001_rate_stated_as_apy(ctx: CheckContext) -> CheckResult:
    """REGDD-STR-001 (structural, Reg_DD, high).
    Trigger: product_type = deposit_account AND >=1 entity rate (v1
    restricts to rate, not percentage — marketing percentages like "72%
    savings" are not yield statements).
    Fail: neither that entity's segment nor any other segment matches
    LEX:APY — a rate of return stated but never as "annual percentage
    yield" (§1030.8(b)).
    Evidence: rate entity_id, raw_text, segment_id; statement that no APY
    token found.
    """
    rates = entities_of_type(ctx, "rate")
    if not _is_deposit(ctx) or not rates:
        return CheckResult(
            check_id="REGDD-STR-001", passed=True, severity="high",
            message="not triggered: no rate entity on a deposit product",
            evidence={"triggered": False},
        )
    apy_hits = segments_matching(ctx, "APY")
    if not apy_hits:
        return CheckResult(
            check_id="REGDD-STR-001", passed=False, severity="high",
            message="a rate of return is advertised but never stated as "
                    "annual percentage yield",
            evidence={"rate_entities": entity_evidence(rates),
                      "apy_lexicon_hits": 0,
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="REGDD-STR-001", passed=True, severity="high",
        message="the advertised rate is accompanied by APY language",
        evidence={"apy_segments": [s.segment_id for s, _ in apy_hits]},
    )


@register_check("REGDD-STR-002", families=["structural"], frameworks=["Reg_DD"],
                scope="asset")
def regdd_str_002_free_account_with_fees(ctx: CheckContext) -> CheckResult:
    """REGDD-STR-002 (structural, Reg_DD, high).
    Trigger: product_type = deposit_account AND LEX:FREE_ACCOUNT matches
    a segment.
    Fail: >=1 entity fee with normalized_value > 0 exists — account
    advertised as free/no-fee while a fee is disclosed elsewhere in the
    same asset (§1030.8(a) misleading-advertisement prohibition).
    Evidence: free-lexicon segment_id + matched span, fee entity ids +
    raw_text + normalized_value.
    """
    free_hits = segments_matching(ctx, "FREE_ACCOUNT")
    if not _is_deposit(ctx) or not free_hits:
        return CheckResult(
            check_id="REGDD-STR-002", passed=True, severity="high",
            message="not triggered: no free-account language on a deposit "
                    "product",
            evidence={"triggered": False},
        )
    fees = [e for e in entities_of_type(ctx, "fee")
            if e.normalized_value is not None and e.normalized_value > 0]
    if fees:
        return CheckResult(
            check_id="REGDD-STR-002", passed=False, severity="high",
            message="account advertised as free while a positive fee is "
                    "disclosed in the same asset",
            evidence={"free_claims": [{"segment_id": s.segment_id,
                                       "matches": m} for s, m in free_hits],
                      "fee_entities": [
                          {"entity_id": e.entity_id, "raw_text": e.raw_text,
                           "normalized_value": e.normalized_value,
                           "segment_id": e.segment_id} for e in fees],
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="REGDD-STR-002", passed=True, severity="high",
        message="free-account language with no contradicting fee entity",
        evidence={"free_segments": [s.segment_id for s, _ in free_hits]},
    )


@register_check("REGDD-STR-003", families=["structural"], frameworks=["Reg_DD"],
                scope="asset")
def regdd_str_003_bonus_needs_conditions(ctx: CheckContext) -> CheckResult:
    """REGDD-STR-003 (structural, Reg_DD, medium).
    Trigger: product_type = deposit_account AND LEX:BONUS matches a segment.
    Fail: zero entities amount AND zero entities time_period in the whole
    asset — a bonus advertised with no quantified condition at all
    (§1030.8(d) requires APY, minimum balance, and time requirements).
    Evidence: bonus segment_id + matched span, entity-type census.
    """
    bonus_hits = segments_matching(ctx, "BONUS")
    if not _is_deposit(ctx) or not bonus_hits:
        return CheckResult(
            check_id="REGDD-STR-003", passed=True, severity="medium",
            message="not triggered: no bonus language on a deposit product",
            evidence={"triggered": False},
        )
    amounts = entities_of_type(ctx, "amount")
    periods = entities_of_type(ctx, "time_period")
    if not amounts and not periods:
        census: dict[str, int] = {}
        for e in ctx.asset.entities:
            census[e.entity_type.value] = census.get(e.entity_type.value, 0) + 1
        return CheckResult(
            check_id="REGDD-STR-003", passed=False, severity="medium",
            message="a bonus is advertised with no quantified condition "
                    "anywhere in the asset",
            evidence={"bonus_claims": [{"segment_id": s.segment_id,
                                        "matches": m} for s, m in bonus_hits],
                      "entity_type_census": census,
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="REGDD-STR-003", passed=True, severity="medium",
        message="bonus language is accompanied by quantified conditions",
        evidence={"amount_entities": len(amounts),
                  "time_period_entities": len(periods)},
    )


@register_check("REGDD-COV-002", families=["coverage"], frameworks=["Reg_DD"])
def regdd_cov_002_deposit_terms_engaged(ctx: CheckContext) -> CheckResult:
    """REGDD-COV-002 (coverage, Reg_DD, high).
    Trigger: product_type = deposit_account AND (REGDD-STR-001/002/003
    trigger fired).
    Fail: no finding with framework = Reg_DD AND none of the triggering
    segments covered.
    Evidence: triggering segment ids.
    """
    if not _is_deposit(ctx):
        return CheckResult(
            check_id="REGDD-COV-002", passed=True, severity="high",
            message="not triggered: not a deposit product",
            evidence={"triggered": False},
        )
    trigger_segs = {e.segment_id for e in entities_of_type(ctx, "rate")}
    trigger_segs |= {s.segment_id for s, _ in segments_matching(ctx, "FREE_ACCOUNT")}
    trigger_segs |= {s.segment_id for s, _ in segments_matching(ctx, "BONUS")}
    if not trigger_segs:
        return CheckResult(
            check_id="REGDD-COV-002", passed=True, severity="high",
            message="not triggered: no deposit-terms triggers",
            evidence={"triggered": False},
        )
    has_regdd_finding = bool(ctx.findings_by_framework.get("Reg_DD"))
    covered = covered_ids(ctx.llm)
    if not has_regdd_finding and not (trigger_segs & covered):
        return CheckResult(
            check_id="REGDD-COV-002", passed=False, severity="high",
            message="deposit-terms triggers present but no Reg DD finding "
                    "exists and no triggering segment was reviewed",
            evidence={"trigger_segment_ids": sorted(trigger_segs),
                      "finding_frameworks": sorted(ctx.findings_by_framework)},
        )
    return CheckResult(
        check_id="REGDD-COV-002", passed=True, severity="high",
        message="the LLM engaged with the deposit-terms triggers",
        evidence={"trigger_segment_ids": sorted(trigger_segs)},
    )


@register_check("REGDD-CON-001", families=["consistency"], frameworks=["*"])
def regdd_con_001_insured_status_misfiled(ctx: CheckContext) -> CheckResult:
    """REGDD-CON-001 (consistency, Reg_DD, medium).
    Trigger: any finding with framework = Reg_DD.
    Fail: the union of its cited segments' text + quoted_evidence matches
    LEX:FDIC AND matches nothing in LEX:DEPOSIT_TERMS — an
    insured-status-only finding filed under Reg DD (belongs to the Part
    328 track, taxonomy §4).
    Evidence: finding_id, matched FDIC lexemes, absence of deposit-terms
    lexemes. Registered universally: a misfiled Reg_DD finding may sit on
    an asset Reg DD was never routed to.
    """
    regdd_findings = ctx.findings_by_framework.get("Reg_DD", [])
    if not regdd_findings:
        return CheckResult(
            check_id="REGDD-CON-001", passed=True, severity="medium",
            message="not triggered: no Reg DD findings",
            evidence={"triggered": False},
        )
    misfiled = []
    for f in regdd_findings:
        texts = [ctx.segment_by_id[i].text for i in f.cited_segment_ids
                 if i in ctx.segment_by_id]
        if f.quoted_evidence:
            texts.append(f.quoted_evidence)
        joined = " ".join(texts)
        fdic = match_lexicon("FDIC", joined)
        deposit = match_lexicon("DEPOSIT_TERMS", joined)
        if fdic and not deposit:
            misfiled.append({"finding_id": f.finding_id,
                             "fdic_lexemes": fdic,
                             "deposit_terms_lexemes": []})
    if misfiled:
        return CheckResult(
            check_id="REGDD-CON-001", passed=False, severity="medium",
            message="insured-status-only evidence filed under Reg DD "
                    "(belongs to the FDIC Part 328 track)",
            evidence={"misfiled_findings": misfiled,
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="REGDD-CON-001", passed=True, severity="medium",
        message="Reg DD findings rest on deposit-terms evidence",
        evidence={"regdd_findings_checked": len(regdd_findings)},
    )


@register_check("REGDD-SEV-001", families=["severity_sanity"], frameworks=["Reg_DD"])
def regdd_sev_001_free_fee_floor(ctx: CheckContext) -> CheckResult:
    """REGDD-SEV-001 (severity_sanity, Reg_DD, medium).
    Trigger: REGDD-STR-002 failed (free + fee) AND a Reg_DD finding with
    verdict = violation cites the free-claim segment.
    Fail: severity = low.
    Evidence: finding_id, severity, REGDD-STR-002 evidence.
    """
    free_hits = segments_matching(ctx, "FREE_ACCOUNT")
    fees = [e for e in entities_of_type(ctx, "fee")
            if e.normalized_value is not None and e.normalized_value > 0]
    str_002_failed = _is_deposit(ctx) and free_hits and fees
    if not str_002_failed:
        return CheckResult(
            check_id="REGDD-SEV-001", passed=True, severity="medium",
            message="not triggered: no free-with-fees contradiction",
            evidence={"triggered": False},
        )
    free_seg_ids = {s.segment_id for s, _ in free_hits}
    underrated = [
        {"finding_id": f.finding_id, "severity": f.severity}
        for f in ctx.findings_by_framework.get("Reg_DD", [])
        if f.verdict == "violation" and f.severity == "low"
        and free_seg_ids & set(f.cited_segment_ids)
    ]
    if underrated:
        return CheckResult(
            check_id="REGDD-SEV-001", passed=False, severity="medium",
            message="Reg DD violation on a free-with-fees contradiction "
                    "rated low",
            evidence={"underrated_findings": underrated,
                      "free_segment_ids": sorted(free_seg_ids),
                      "fee_entity_ids": [e.entity_id for e in fees]},
        )
    return CheckResult(
        check_id="REGDD-SEV-001", passed=True, severity="medium",
        message="no underrated Reg DD violations on the free-fee "
                "contradiction",
        evidence={"free_segment_ids": sorted(free_seg_ids)},
    )

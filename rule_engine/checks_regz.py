"""Reg Z / TILA checks — §2 of docs/check_taxonomy.md (12 CFR 1026.16/.24).

The most mechanizable framework: §1026.24(d)(1) triggering terms are
enumerable facts the deterministic entity layer already extracts. All
checks register under TILA routing except REGZ-CON-001, which polices
misfiled TILA findings and therefore runs universally.
One function per check_id; docstring = taxonomy row.
"""

from __future__ import annotations

from rule_engine.core import CheckContext, CheckResult, register_check
from rule_engine.lexicons import (
    APR_HEIGHT_RATIO_MIN,
    CLOSED_END_PRODUCTS,
    CREDIT_PRODUCTS,
    LEXICON_VERSION,
    OPEN_END_PRODUCTS,
    PROX_MAX,
    THRESHOLDS_VERSION,
    covered_ids,
    entities_of_type,
    entity_evidence,
    heights_by_segment,
    match_lexicon,
    proximity_findings,
    segments_matching,
)


def _closed_end_trigger(ctx: CheckContext):
    """§1026.24(d)(1) trigger-term state: (triggered, trigger_segment_ids,
    evidence). Trigger = closed-end credit product AND (amount+time_period
    entities co-occur OR LEX:TILA_TRIGGER matches a segment)."""
    product = ctx.asset.routing.product_type.value
    if product not in CLOSED_END_PRODUCTS:
        return False, set(), {"product_type": product}
    amounts = entities_of_type(ctx, "amount")
    periods = entities_of_type(ctx, "time_period")
    lex_hits = segments_matching(ctx, "TILA_TRIGGER")
    triggered = bool((amounts and periods) or lex_hits)
    segs: set[str] = set()
    if triggered:
        if amounts and periods:
            segs |= {e.segment_id for e in amounts + periods}
        segs |= {s.segment_id for s, _ in lex_hits}
    evidence = {
        "product_type": product,
        "trigger_entities": entity_evidence(amounts + periods),
        "trigger_lexicon_hits": [{"segment_id": s.segment_id, "matches": m}
                                 for s, m in lex_hits],
        "lexicon_version": LEXICON_VERSION,
    }
    return triggered, segs, evidence


def _apr_presence(ctx: CheckContext):
    """(apr entities, segments matching LEX:APR)."""
    return entities_of_type(ctx, "apr"), segments_matching(ctx, "APR")


@register_check("REGZ-COV-001", families=["coverage"], frameworks=["TILA"])
def regz_cov_001_tila_evaluated(ctx: CheckContext) -> CheckResult:
    """REGZ-COV-001 (coverage, TILA, high).
    Trigger: "TILA" in A.routing.frameworks.
    Fail: "TILA" not in L.frameworks_evaluated.
    Evidence: routing.frameworks, frameworks_evaluated.
    """
    ok = "TILA" in ctx.llm.frameworks_evaluated
    return CheckResult(
        check_id="REGZ-COV-001", passed=ok, severity="high",
        message="TILA was evaluated" if ok
        else "asset routes to TILA but the LLM never evaluated it",
        evidence={"routed": sorted(ctx.routed_frameworks),
                  "frameworks_evaluated": ctx.llm.frameworks_evaluated},
    )


@register_check("REGZ-STR-001", families=["structural"], frameworks=["TILA"],
                scope="asset")
def regz_str_001_trigger_terms_require_apr(ctx: CheckContext) -> CheckResult:
    """REGZ-STR-001 (structural, TILA, high).
    Trigger: CREDIT (closed-end) AND trigger terms present: (entity amount
    AND entity time_period both exist) OR LEX:TILA_TRIGGER matches a
    segment — §1026.24(d)(1).
    Fail: no entity apr exists AND no segment matches LEX:APR — triggering
    terms advertised without the §1026.24(d)(2)(ii) APR disclosure.
    Evidence: triggering entity ids (raw_text, segment_id, char_span) or
    lexicon hits; statement that no APR entity/token found.
    """
    triggered, _, evidence = _closed_end_trigger(ctx)
    if not triggered:
        return CheckResult(
            check_id="REGZ-STR-001", passed=True, severity="high",
            message="not triggered: no §1026.24(d)(1) trigger terms",
            evidence={"triggered": False,
                      "product_type": evidence["product_type"]},
        )
    apr_ents, apr_lex = _apr_presence(ctx)
    if not apr_ents and not apr_lex:
        evidence["apr_entities_found"] = 0
        evidence["apr_lexicon_hits"] = 0
        return CheckResult(
            check_id="REGZ-STR-001", passed=False, severity="high",
            message="§1026.24(d)(1) trigger terms advertised with no APR "
                    "disclosure anywhere in the asset",
            evidence=evidence,
        )
    return CheckResult(
        check_id="REGZ-STR-001", passed=True, severity="high",
        message="trigger terms are accompanied by an APR disclosure",
        evidence={"apr_entity_ids": [e.entity_id for e in apr_ents],
                  "apr_lexicon_segments": [s.segment_id for s, _ in apr_lex]},
    )


@register_check("REGZ-STR-002", families=["structural"], frameworks=["TILA"],
                scope="asset")
def regz_str_002_rate_stated_as_apr(ctx: CheckContext) -> CheckResult:
    """REGZ-STR-002 (structural, TILA, high).
    Trigger: CREDIT AND >=1 entity rate.
    Fail: zero entities apr AND the rate entity's segment does not match
    LEX:APR — a finance rate stated but never as an annual percentage
    rate (§1026.24(c) closed-end / §1026.16(b)(2) open-end).
    Evidence: rate entity_id, raw_text, segment_id.
    """
    product = ctx.asset.routing.product_type.value
    rates = entities_of_type(ctx, "rate")
    if product not in CREDIT_PRODUCTS or not rates:
        return CheckResult(
            check_id="REGZ-STR-002", passed=True, severity="high",
            message="not triggered: no rate entity on a credit product",
            evidence={"triggered": False, "product_type": product},
        )
    if entities_of_type(ctx, "apr"):
        return CheckResult(
            check_id="REGZ-STR-002", passed=True, severity="high",
            message="an APR entity accompanies the advertised rate",
            evidence={"rate_entity_ids": [e.entity_id for e in rates]},
        )
    unqualified = [e for e in rates
                   if not match_lexicon("APR", ctx.segment_by_id[e.segment_id].text)]
    if unqualified:
        return CheckResult(
            check_id="REGZ-STR-002", passed=False, severity="high",
            message="a finance rate is advertised but never stated as an "
                    "annual percentage rate",
            evidence={"unqualified_rate_entities": entity_evidence(unqualified),
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="REGZ-STR-002", passed=True, severity="high",
        message="every advertised rate is stated as APR in its segment",
        evidence={"rate_entity_ids": [e.entity_id for e in rates]},
    )


@register_check("REGZ-STR-003", families=["structural"], frameworks=["TILA"],
                scope="asset")
def regz_str_003_open_end_fee_needs_apr(ctx: CheckContext) -> CheckResult:
    """REGZ-STR-003 (structural, TILA, medium).
    Trigger: A.routing.product_type in {credit_card, bnpl} AND >=1 entity
    fee (open-end §1026.6-type charge advertised).
    Fail: no entity apr AND no LEX:APR match anywhere (§1026.16(b)(1)
    disclosure absent).
    Evidence: fee entity ids + raw_text.
    """
    product = ctx.asset.routing.product_type.value
    fees = entities_of_type(ctx, "fee")
    if product not in OPEN_END_PRODUCTS or not fees:
        return CheckResult(
            check_id="REGZ-STR-003", passed=True, severity="medium",
            message="not triggered: no fee entity on an open-end product",
            evidence={"triggered": False, "product_type": product},
        )
    apr_ents, apr_lex = _apr_presence(ctx)
    if not apr_ents and not apr_lex:
        return CheckResult(
            check_id="REGZ-STR-003", passed=False, severity="medium",
            message="open-end charges advertised with no APR disclosure "
                    "anywhere in the asset",
            evidence={"fee_entities": entity_evidence(fees),
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="REGZ-STR-003", passed=True, severity="medium",
        message="advertised charges are accompanied by an APR disclosure",
        evidence={"fee_entity_ids": [e.entity_id for e in fees]},
    )


@register_check("REGZ-STR-004", families=["structural"], frameworks=["TILA"],
                scope="asset")
def regz_str_004_apr_prominence_floor(ctx: CheckContext) -> CheckResult:
    """REGZ-STR-004 (structural, TILA, medium).
    Trigger: REGZ-STR-001 trigger fired AND an apr entity exists AND both
    its segment and a triggering segment have bboxes.
    Fail: text_height_percent(APR segment) < APR_HEIGHT_RATIO_MIN x
    text_height_percent(triggering segment) OR disclosure_proximity
    (trigger seg -> APR seg) > PROX_MAX — clear-and-conspicuous floor on
    the mandated disclosure.
    Evidence: both cv finding_ids + values, threshold name+version, both
    segment ids. Clauses without CV measurements are not evaluable and
    are skipped (measurement absence is not a violation).
    """
    triggered, trigger_segs, _ = _closed_end_trigger(ctx)
    apr_ents = entities_of_type(ctx, "apr")
    if not triggered or not apr_ents:
        return CheckResult(
            check_id="REGZ-STR-004", passed=True, severity="medium",
            message="not triggered: needs trigger terms plus an APR entity",
            evidence={"triggered": False},
        )
    apr_segs = {e.segment_id for e in apr_ents}
    heights = heights_by_segment(ctx)
    violations = []

    trigger_heights = {s: heights[s] for s in trigger_segs if s in heights}
    apr_heights = {s: heights[s] for s in apr_segs if s in heights}
    if trigger_heights and apr_heights:
        trig_seg, trig_h = max(trigger_heights.items(), key=lambda kv: kv[1])
        apr_seg, apr_h = max(apr_heights.items(), key=lambda kv: kv[1])
        if apr_h < APR_HEIGHT_RATIO_MIN * trig_h:
            violations.append({
                "clause": "height_ratio",
                "trigger_segment_id": trig_seg, "trigger_height": trig_h,
                "apr_segment_id": apr_seg, "apr_height": apr_h,
                "required_min": APR_HEIGHT_RATIO_MIN * trig_h,
            })
    pairs = [f for f in proximity_findings(ctx)
             if f.segment_id in trigger_segs and f.related_segment_id in apr_segs]
    if pairs:
        nearest = min(pairs, key=lambda f: f.value)
        if nearest.value > PROX_MAX:
            violations.append({
                "clause": "proximity",
                "proximity_finding_id": nearest.finding_id,
                "trigger_segment_id": nearest.segment_id,
                "apr_segment_id": nearest.related_segment_id,
                "proximity": nearest.value,
            })
    if violations:
        return CheckResult(
            check_id="REGZ-STR-004", passed=False, severity="medium",
            message="mandated APR disclosure fails the clear-and-conspicuous "
                    "floor relative to the triggering terms",
            evidence={"violations": violations,
                      "thresholds": {"APR_HEIGHT_RATIO_MIN": APR_HEIGHT_RATIO_MIN,
                                     "PROX_MAX": PROX_MAX},
                      "thresholds_version": THRESHOLDS_VERSION},
        )
    return CheckResult(
        check_id="REGZ-STR-004", passed=True, severity="medium",
        message="APR disclosure meets the measurable prominence floor "
                "(unmeasured clauses skipped)",
        evidence={"height_clause_evaluable": bool(trigger_heights and apr_heights),
                  "proximity_clause_evaluable": bool(pairs),
                  "thresholds_version": THRESHOLDS_VERSION},
    )


@register_check("REGZ-COV-002", families=["coverage"], frameworks=["TILA"])
def regz_cov_002_trigger_terms_engaged(ctx: CheckContext) -> CheckResult:
    """REGZ-COV-002 (coverage, TILA, high).
    Trigger: REGZ-STR-001 trigger fired (triggering terms present).
    Fail: no finding with framework = TILA exists AND none of the
    trigger-bearing segments are covered — the LLM never engaged with the
    trigger-term geometry.
    Evidence: trigger-bearing segment ids, list of frameworks in findings.
    """
    triggered, trigger_segs, _ = _closed_end_trigger(ctx)
    if not triggered:
        return CheckResult(
            check_id="REGZ-COV-002", passed=True, severity="high",
            message="not triggered: no trigger terms",
            evidence={"triggered": False},
        )
    has_tila_finding = bool(ctx.findings_by_framework.get("TILA"))
    covered = covered_ids(ctx.llm)
    if not has_tila_finding and not (trigger_segs & covered):
        return CheckResult(
            check_id="REGZ-COV-002", passed=False, severity="high",
            message="trigger terms present but no TILA finding exists and "
                    "no trigger-bearing segment was reviewed",
            evidence={"trigger_segment_ids": sorted(trigger_segs),
                      "finding_frameworks":
                      sorted(ctx.findings_by_framework)},
        )
    return CheckResult(
        check_id="REGZ-COV-002", passed=True, severity="high",
        message="the LLM engaged with the trigger-term geometry",
        evidence={"trigger_segment_ids": sorted(trigger_segs),
                  "tila_findings": len(ctx.findings_by_framework.get("TILA", []))},
    )


@register_check("REGZ-SEV-001", families=["severity_sanity"], frameworks=["TILA"])
def regz_sev_001_missing_apr_floor(ctx: CheckContext) -> CheckResult:
    """REGZ-SEV-001 (severity_sanity, TILA, medium).
    Trigger: REGZ-STR-001 failed (triggered, no APR anywhere) AND a TILA
    finding with verdict = violation exists.
    Fail: that finding's severity in {medium, low} — omission of a
    mandatory disclosure has a floor of high.
    Evidence: finding_id, severity, REGZ-STR-001 evidence.
    """
    triggered, _, trig_evidence = _closed_end_trigger(ctx)
    apr_ents, apr_lex = _apr_presence(ctx)
    str_001_failed = triggered and not apr_ents and not apr_lex
    if not str_001_failed:
        return CheckResult(
            check_id="REGZ-SEV-001", passed=True, severity="medium",
            message="not triggered: mandatory APR disclosure is not missing",
            evidence={"triggered": False},
        )
    underrated = [
        {"finding_id": f.finding_id, "severity": f.severity}
        for f in ctx.findings_by_framework.get("TILA", [])
        if f.verdict == "violation" and f.severity in ("medium", "low")
    ]
    if underrated:
        return CheckResult(
            check_id="REGZ-SEV-001", passed=False, severity="medium",
            message="TILA violation for a missing mandatory disclosure "
                    "rated below high",
            evidence={"underrated_findings": underrated,
                      "trigger_evidence": trig_evidence},
        )
    return CheckResult(
        check_id="REGZ-SEV-001", passed=True, severity="medium",
        message="no underrated TILA violations for the missing disclosure",
        evidence={"tila_violations_checked":
                  sum(1 for f in ctx.findings_by_framework.get("TILA", [])
                      if f.verdict == "violation")},
    )


@register_check("REGZ-CON-001", families=["consistency"], frameworks=["*"])
def regz_con_001_tila_finding_needs_credit_signals(ctx: CheckContext) -> CheckResult:
    """REGZ-CON-001 (consistency, TILA, low).
    Trigger: any finding with framework = TILA.
    Fail: NOT CREDIT AND zero apr/rate entities exist — TILA finding on
    an asset with no credit signals (advisory: likely misfiled framework).
    Evidence: finding_id, product_type, entity-type census.
    Registered universally: a misfiled TILA finding is precisely the case
    where TILA may be absent from routing.
    """
    tila_findings = ctx.findings_by_framework.get("TILA", [])
    if not tila_findings:
        return CheckResult(
            check_id="REGZ-CON-001", passed=True, severity="low",
            message="not triggered: no TILA findings",
            evidence={"triggered": False},
        )
    product = ctx.asset.routing.product_type.value
    credit_signals = entities_of_type(ctx, "apr", "rate")
    if product not in CREDIT_PRODUCTS and not credit_signals:
        census: dict[str, int] = {}
        for e in ctx.asset.entities:
            census[e.entity_type.value] = census.get(e.entity_type.value, 0) + 1
        return CheckResult(
            check_id="REGZ-CON-001", passed=False, severity="low",
            message="TILA findings on an asset with no credit signals "
                    "(likely misfiled framework)",
            evidence={"finding_ids": [f.finding_id for f in tila_findings],
                      "product_type": product,
                      "entity_type_census": census},
        )
    return CheckResult(
        check_id="REGZ-CON-001", passed=True, severity="low",
        message="TILA findings are backed by credit signals",
        evidence={"product_type": product,
                  "credit_signal_entities":
                  [e.entity_id for e in credit_signals]},
    )

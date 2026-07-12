"""UNIVERSAL checks — §0 of docs/check_taxonomy.md.

Framework-agnostic engine core: these run on every asset/output pair
regardless of routing. One function per check_id; each docstring is the
taxonomy row it implements. Importing this module populates
``rule_engine.core.CHECK_REGISTRY``.

Determinism guard (see rule_engine/core.py): stdlib + contract modules
only. The numeric tolerance below is a versioned constant per
docs/check_taxonomy.md Appendix B.
"""

from __future__ import annotations

import re

from rule_engine.core import CheckContext, CheckResult, register_check
from schema import Framework

#: Appendix B, v1: max abs difference between a unit-normalized quoted
#: numeric and an entity normalized_value (equal after rounding to 2 dp).
NUM_TOL = 0.005
THRESHOLDS_VERSION = "v1"

_MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?")
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s?%")


def _norm(text: str) -> str:
    """Whitespace normalization: collapse runs; no other transformation."""
    return " ".join(text.split())


@register_check("ALL-GRD-001", families=["grounding"], frameworks=["*"])
def all_grd_001_cited_segments_resolve(ctx: CheckContext) -> CheckResult:
    """ALL-GRD-001 (grounding, ALL, high).
    Trigger: any finding in L.findings.
    Fail: some cited_segment_ids entry not in A.segments[*].segment_id.
    Evidence: finding_id, unresolved id(s), list of valid segment ids.
    """
    unresolved = [
        {"finding_id": f.finding_id,
         "missing_segment_ids": [i for i in f.cited_segment_ids
                                 if i not in ctx.segment_by_id]}
        for f in ctx.llm.findings
        if any(i not in ctx.segment_by_id for i in f.cited_segment_ids)
    ]
    if unresolved:
        return CheckResult(
            check_id="ALL-GRD-001", passed=False, severity="high",
            message="findings cite segment ids that do not exist in the asset",
            evidence={"unresolved": unresolved,
                      "valid_segment_ids": sorted(ctx.segment_by_id)},
        )
    return CheckResult(
        check_id="ALL-GRD-001", passed=True, severity="high",
        message="all cited segment ids resolve",
        evidence={"findings_checked": len(ctx.llm.findings)},
    )


@register_check("ALL-GRD-002", families=["grounding"], frameworks=["*"])
def all_grd_002_cited_entities_resolve(ctx: CheckContext) -> CheckResult:
    """ALL-GRD-002 (grounding, ALL, high).
    Trigger: any finding.
    Fail: some cited_entity_ids entry not in A.entities[*].entity_id.
    Evidence: finding_id, unresolved id(s).
    """
    unresolved = [
        {"finding_id": f.finding_id,
         "missing_entity_ids": [i for i in f.cited_entity_ids
                                if i not in ctx.entity_by_id]}
        for f in ctx.llm.findings
        if any(i not in ctx.entity_by_id for i in f.cited_entity_ids)
    ]
    if unresolved:
        return CheckResult(
            check_id="ALL-GRD-002", passed=False, severity="high",
            message="findings cite entity ids that do not exist in the asset",
            evidence={"unresolved": unresolved},
        )
    return CheckResult(
        check_id="ALL-GRD-002", passed=True, severity="high",
        message="all cited entity ids resolve",
        evidence={"findings_checked": len(ctx.llm.findings)},
    )


@register_check("ALL-GRD-003", families=["grounding"], frameworks=["*"])
def all_grd_003_claim_ids_resolve(ctx: CheckContext) -> CheckResult:
    """ALL-GRD-003 (grounding, ALL, high).
    Trigger: any finding with claim_candidate_id set.
    Fail: id not in A.claim_candidates[*].claim_id.
    Evidence: finding_id, unresolved id.
    """
    unresolved = [
        {"finding_id": f.finding_id, "missing_claim_id": f.claim_candidate_id}
        for f in ctx.llm.findings
        if f.claim_candidate_id and f.claim_candidate_id not in ctx.claim_by_id
    ]
    if unresolved:
        return CheckResult(
            check_id="ALL-GRD-003", passed=False, severity="high",
            message="findings reference claim candidates that do not exist",
            evidence={"unresolved": unresolved,
                      "valid_claim_ids": sorted(ctx.claim_by_id)},
        )
    return CheckResult(
        check_id="ALL-GRD-003", passed=True, severity="high",
        message="all claim_candidate_id references resolve",
        evidence={"findings_checked": len(ctx.llm.findings)},
    )


@register_check("ALL-GRD-004", families=["grounding"], frameworks=["*"])
def all_grd_004_quotes_verbatim(ctx: CheckContext) -> CheckResult:
    """ALL-GRD-004 (grounding, ALL, high).
    Trigger: any finding with quoted_evidence set.
    Fail: whitespace-normalized quote is not a substring of any cited
    segment's normalized text (of all segments if no segments cited).
    Evidence: finding_id, quote, texts of cited segments.
    """
    failures = []
    for f in ctx.llm.findings:
        if not f.quoted_evidence:
            continue
        if f.cited_segment_ids:
            search = [ctx.segment_by_id[i] for i in f.cited_segment_ids
                      if i in ctx.segment_by_id]
        else:
            search = list(ctx.asset.segments)
        quote = _norm(f.quoted_evidence)
        if not any(quote in _norm(s.text) for s in search):
            failures.append({
                "finding_id": f.finding_id,
                "quote": f.quoted_evidence,
                "searched_segments": {s.segment_id: s.text for s in search},
            })
    if failures:
        return CheckResult(
            check_id="ALL-GRD-004", passed=False, severity="high",
            message="quoted_evidence does not appear verbatim in cited text",
            evidence={"unmatched_quotes": failures},
        )
    return CheckResult(
        check_id="ALL-GRD-004", passed=True, severity="high",
        message="every quote appears verbatim in cited text",
        evidence={"quotes_checked":
                  sum(1 for f in ctx.llm.findings if f.quoted_evidence)},
    )


@register_check("ALL-GRD-005", families=["grounding"], frameworks=["*"])
def all_grd_005_reviewed_clear_resolves(ctx: CheckContext) -> CheckResult:
    """ALL-GRD-005 (grounding, ALL, medium).
    Trigger: L.reviewed_clear non-empty.
    Fail: some entry resolves to neither a segment_id nor a claim_id in A
    — grounding-flavored coverage: an LLM cannot claim to have reviewed
    something that doesn't exist.
    Evidence: the unresolvable entries plus counts of valid ids.
    """
    unresolved = [e for e in ctx.llm.reviewed_clear
                  if e not in ctx.segment_by_id and e not in ctx.claim_by_id]
    if unresolved:
        return CheckResult(
            check_id="ALL-GRD-005", passed=False, severity="medium",
            message="reviewed_clear lists ids that do not exist in the asset",
            evidence={"unresolved_entries": unresolved,
                      "valid_segment_ids": len(ctx.segment_by_id),
                      "valid_claim_ids": len(ctx.claim_by_id)},
        )
    return CheckResult(
        check_id="ALL-GRD-005", passed=True, severity="medium",
        message="all reviewed_clear entries resolve",
        evidence={"entries_checked": len(ctx.llm.reviewed_clear),
                  "valid_segment_ids": len(ctx.segment_by_id),
                  "valid_claim_ids": len(ctx.claim_by_id)},
    )


@register_check("ALL-GRD-006", families=["grounding"], frameworks=["*"])
def all_grd_006_adverse_findings_cite(ctx: CheckContext) -> CheckResult:
    """ALL-GRD-006 (grounding, ALL, high).
    Trigger: any finding with verdict in {violation, potential_violation}.
    Fail: cited_segment_ids empty AND cited_entity_ids empty AND
    claim_candidate_id null.
    Evidence: finding_id, verdict, framework.
    """
    floating = [
        {"finding_id": f.finding_id, "verdict": f.verdict,
         "framework": f.framework.value}
        for f in ctx.llm.findings
        if f.verdict in ("violation", "potential_violation")
        and not f.cited_segment_ids and not f.cited_entity_ids
        and not f.claim_candidate_id
    ]
    if floating:
        return CheckResult(
            check_id="ALL-GRD-006", passed=False, severity="high",
            message="adverse findings cite no segment, entity, or claim",
            evidence={"uncited_adverse_findings": floating},
        )
    return CheckResult(
        check_id="ALL-GRD-006", passed=True, severity="high",
        message="every adverse finding cites at least one id",
        evidence={"adverse_findings_checked":
                  sum(1 for f in ctx.llm.findings
                      if f.verdict in ("violation", "potential_violation"))},
    )


@register_check("ALL-GRD-007", families=["grounding"], frameworks=["*"])
def all_grd_007_quoted_numerics_match(ctx: CheckContext) -> CheckResult:
    """ALL-GRD-007 (grounding, ALL, medium).
    Trigger: any finding whose quoted_evidence contains money- or
    percent-shaped numeric tokens ($X[,XXX][.XX], X[.X]% — deliberately
    excludes bare counts/years like "8.3 times" or "Forbes 2025", which
    the entity layer does not extract).
    Fail: some such token, after unit normalization ($ stripped, % kept
    as the number), matches no entity's non-null normalized_value within
    NUM_TOL — either the LLM misquoted a regulated figure or the
    deterministic extractor missed it; both must surface.
    Evidence: finding_id, unmatched token(s) + parsed value, nearest
    entity normalized_value(s), NUM_TOL version.
    """
    values = [(e.entity_id, e.normalized_value) for e in ctx.asset.entities
              if e.normalized_value is not None]
    unmatched = []
    tokens_checked = 0
    for f in ctx.llm.findings:
        if not f.quoted_evidence:
            continue
        tokens = ([(t, float(t.lstrip("$ ").replace(",", "")))
                   for t in _MONEY_RE.findall(f.quoted_evidence)]
                  + [(t, float(t.rstrip("% ")))
                     for t in _PERCENT_RE.findall(f.quoted_evidence)])
        tokens_checked += len(tokens)
        for token, parsed in tokens:
            if any(abs(parsed - v) <= NUM_TOL for _, v in values):
                continue
            nearest = sorted(values, key=lambda ev: abs(parsed - ev[1]))[:3]
            unmatched.append({
                "finding_id": f.finding_id, "token": token, "parsed": parsed,
                "nearest_entities": [
                    {"entity_id": i, "normalized_value": v} for i, v in nearest
                ],
            })
    if unmatched:
        return CheckResult(
            check_id="ALL-GRD-007", passed=False, severity="medium",
            message="quoted money/percent figures match no extracted entity "
                    "value (LLM misquote or extraction gap)",
            evidence={"unmatched_tokens": unmatched, "num_tol": NUM_TOL,
                      "thresholds_version": THRESHOLDS_VERSION},
        )
    return CheckResult(
        check_id="ALL-GRD-007", passed=True, severity="medium",
        message="all quoted money/percent figures match extracted entities",
        evidence={"tokens_checked": tokens_checked, "num_tol": NUM_TOL,
                  "thresholds_version": THRESHOLDS_VERSION},
    )


@register_check("ALL-CON-001", families=["consistency"], frameworks=["*"])
def all_con_001_asset_id_match(ctx: CheckContext) -> CheckResult:
    """ALL-CON-001 (consistency, ALL, critical).
    Trigger: always.
    Fail: L.asset_id != A.asset_id.
    Evidence: both ids.
    """
    ok = ctx.llm.asset_id == ctx.asset.asset_id
    return CheckResult(
        check_id="ALL-CON-001", passed=ok, severity="critical",
        message="asset ids agree" if ok
        else "the LLM output reviews a different asset",
        evidence={"asset.asset_id": ctx.asset.asset_id,
                  "llm.asset_id": ctx.llm.asset_id},
    )


@register_check("ALL-CON-002", families=["consistency"], frameworks=["*"])
def all_con_002_cleared_not_violated(ctx: CheckContext) -> CheckResult:
    """ALL-CON-002 (consistency, ALL, high).
    Trigger: any claim_id or segment_id in L.reviewed_clear.
    Fail: same id is also cited by an adverse finding (claim_candidate_id
    match for claims; cited_segment_ids match for segments).
    Evidence: the id, the adverse finding_id.
    """
    adverse = [f for f in ctx.llm.findings
               if f.verdict in ("violation", "potential_violation")]
    contradictions = []
    for entry in ctx.llm.reviewed_clear:
        for f in adverse:
            if entry == f.claim_candidate_id or entry in f.cited_segment_ids:
                contradictions.append(
                    {"cleared_id": entry, "adverse_finding_id": f.finding_id,
                     "verdict": f.verdict}
                )
    if contradictions:
        return CheckResult(
            check_id="ALL-CON-002", passed=False, severity="high",
            message="ids marked clear are also cited by adverse findings",
            evidence={"contradictions": contradictions},
        )
    return CheckResult(
        check_id="ALL-CON-002", passed=True, severity="high",
        message="no cleared id is cited by an adverse finding",
        evidence={"cleared_checked": len(ctx.llm.reviewed_clear),
                  "adverse_findings": len(adverse)},
    )


@register_check("ALL-CON-003", families=["consistency"], frameworks=["*"])
def all_con_003_frameworks_valid(ctx: CheckContext) -> CheckResult:
    """ALL-CON-003 (consistency, ALL, medium).
    Trigger: L.frameworks_evaluated non-empty.
    Fail: some entry is not a valid Framework enum value.
    Evidence: invalid entries, valid enum values.
    """
    valid = {f.value for f in Framework}
    invalid = [e for e in ctx.llm.frameworks_evaluated if e not in valid]
    if invalid:
        return CheckResult(
            check_id="ALL-CON-003", passed=False, severity="medium",
            message="frameworks_evaluated contains unknown framework values",
            evidence={"invalid_entries": invalid,
                      "valid_values": sorted(valid)},
        )
    return CheckResult(
        check_id="ALL-CON-003", passed=True, severity="medium",
        message="all evaluated frameworks are valid enum values",
        evidence={"entries_checked": len(ctx.llm.frameworks_evaluated)},
    )


@register_check("ALL-CON-004", families=["consistency"], frameworks=["*"])
def all_con_004_compliant_severity(ctx: CheckContext) -> CheckResult:
    """ALL-CON-004 (consistency, ALL, medium).
    Trigger: any finding with verdict = compliant.
    Fail: severity in {critical, high}.
    Evidence: finding_id, verdict, severity.
    """
    incoherent = [
        {"finding_id": f.finding_id, "verdict": f.verdict,
         "severity": f.severity}
        for f in ctx.llm.findings
        if f.verdict == "compliant" and f.severity in ("critical", "high")
    ]
    if incoherent:
        return CheckResult(
            check_id="ALL-CON-004", passed=False, severity="medium",
            message="compliant findings carry critical/high severity",
            evidence={"incoherent_findings": incoherent},
        )
    return CheckResult(
        check_id="ALL-CON-004", passed=True, severity="medium",
        message="compliant findings carry sane severities",
        evidence={"compliant_findings_checked":
                  sum(1 for f in ctx.llm.findings if f.verdict == "compliant")},
    )


@register_check("ALL-CON-005", families=["consistency"], frameworks=["*"])
def all_con_005_finding_framework_evaluated(ctx: CheckContext) -> CheckResult:
    """ALL-CON-005 (consistency, ALL, medium).
    Trigger: any finding.
    Fail: finding.framework not in L.frameworks_evaluated (finding issued
    under a framework the LLM says it did not evaluate).
    Evidence: finding_id, framework, frameworks_evaluated.
    """
    evaluated = set(ctx.llm.frameworks_evaluated)
    orphans = [
        {"finding_id": f.finding_id, "framework": f.framework.value}
        for f in ctx.llm.findings if f.framework.value not in evaluated
    ]
    if orphans:
        return CheckResult(
            check_id="ALL-CON-005", passed=False, severity="medium",
            message="findings issued under frameworks not in "
                    "frameworks_evaluated",
            evidence={"orphan_findings": orphans,
                      "frameworks_evaluated": ctx.llm.frameworks_evaluated},
        )
    return CheckResult(
        check_id="ALL-CON-005", passed=True, severity="medium",
        message="every finding's framework was evaluated",
        evidence={"findings_checked": len(ctx.llm.findings)},
    )


@register_check("ALL-COV-001", families=["coverage"], frameworks=["*"])
def all_cov_001_routed_frameworks_evaluated(ctx: CheckContext) -> CheckResult:
    """ALL-COV-001 (coverage, ALL, high).
    Trigger: always.
    Fail: A.routing.frameworks not a subset of L.frameworks_evaluated.
    Evidence: missing frameworks, A.routing.signal (router audit trail).
    """
    missing = sorted(ctx.routed_frameworks - set(ctx.llm.frameworks_evaluated))
    if missing:
        return CheckResult(
            check_id="ALL-COV-001", passed=False, severity="high",
            message="routed frameworks were not evaluated by the LLM",
            evidence={"missing_frameworks": missing,
                      "routed": sorted(ctx.routed_frameworks),
                      "frameworks_evaluated": ctx.llm.frameworks_evaluated,
                      "routing_signal": ctx.asset.routing.signal},
        )
    return CheckResult(
        check_id="ALL-COV-001", passed=True, severity="high",
        message="every routed framework was evaluated",
        evidence={"routed": sorted(ctx.routed_frameworks)},
    )


@register_check("ALL-COV-002", families=["coverage"], frameworks=["*"])
def all_cov_002_claims_addressed(ctx: CheckContext) -> CheckResult:
    """ALL-COV-002 (coverage, ALL, high).
    Trigger: A.claim_candidates non-empty.
    Fail: some claim_id not covered — not in (findings[*].claim_candidate_id
    union L.reviewed_clear).
    Evidence: uncovered claim ids, their claim_type, text, segment_id.
    """
    uncovered = [
        {"claim_id": c.claim_id, "claim_type": c.claim_type.value,
         "text": c.text, "segment_id": c.segment_id}
        for c in ctx.asset.claim_candidates
        if c.claim_id not in ctx.addressed_claim_ids
    ]
    if uncovered:
        return CheckResult(
            check_id="ALL-COV-002", passed=False, severity="high",
            message="claim candidates neither addressed by a finding nor "
                    "marked reviewed_clear",
            evidence={"unaddressed_claims": uncovered,
                      "unaddressed_claim_ids":
                      [c["claim_id"] for c in uncovered]},
        )
    return CheckResult(
        check_id="ALL-COV-002", passed=True, severity="high",
        message="every claim candidate is addressed",
        evidence={"claims_checked": len(ctx.asset.claim_candidates)},
    )


@register_check("ALL-STR-001", families=["structural"], frameworks=["*"])
def all_str_001_llm_meta_complete(ctx: CheckContext) -> CheckResult:
    """ALL-STR-001 (structural, ALL, low).
    Trigger: always.
    Fail: L.llm_meta missing key 'model' or 'prompt_version' (audit-chain
    completeness; values are opaque).
    Evidence: present/missing keys.
    """
    required = ("model", "prompt_version")
    missing = [k for k in required if k not in ctx.llm.llm_meta]
    if missing:
        return CheckResult(
            check_id="ALL-STR-001", passed=False, severity="low",
            message="llm_meta lacks audit-chain keys",
            evidence={"missing_keys": missing,
                      "present_keys": sorted(ctx.llm.llm_meta)},
        )
    return CheckResult(
        check_id="ALL-STR-001", passed=True, severity="low",
        message="llm_meta audit keys present",
        evidence={"present_keys": sorted(ctx.llm.llm_meta)},
    )

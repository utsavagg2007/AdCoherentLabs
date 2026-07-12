"""State UDAP checks — §6 of docs/check_taxonomy.md.

State consumer-protection statutes are predominantly FTC §5 analogues
("little FTC acts"), so these checks mirror the FTC5 logic once,
parameterized per state from state_udap_table.py (taxonomy Appendix D)
— never 50 near-copies. Each check iterates the asset's user-supplied
``target_jurisdictions`` and produces per-state evidence carrying that
state's own statute citation: the citation is the audit-trail payload
downstream.

All checks gate on STATE_UDAP routing, which the router emits only when
target_jurisdictions contains a state code — no states, no state checks.
One function per check_id; docstring = taxonomy row.
"""

from __future__ import annotations

import re

from rule_engine.core import CheckContext, CheckResult, register_check
from rule_engine.lexicons import CREDIT_PRODUCTS
from rule_engine.state_udap_table import STATE_TABLE_VERSION, STATE_UDAP_TABLE

_STATE_CODE_RE = re.compile(r"US-[A-Z]{2}")

_UNKNOWN_ROW = {"statute": f"not in state table {STATE_TABLE_VERSION}",
                "name": "unknown jurisdiction",
                "credit_exempt": False,
                "notes": "jurisdiction missing from the compiled table"}


def _targeted_states(ctx: CheckContext) -> list[str]:
    """US state codes among target_jurisdictions, deduped, order kept."""
    seen: dict[str, None] = {}
    for c in ctx.asset.target_jurisdictions:
        if _STATE_CODE_RE.fullmatch(c):
            seen.setdefault(c)
    return list(seen)


def _row(state: str) -> dict:
    return STATE_UDAP_TABLE.get(state, _UNKNOWN_ROW)


def _cite(state: str) -> dict:
    return {"state": state, "statute": _row(state)["statute"]}


def _state_findings(ctx: CheckContext) -> list:
    return ctx.findings_by_framework.get("STATE_UDAP", [])


@register_check("STATE-COV-001", families=["coverage"],
                frameworks=["STATE_UDAP"])
def state_cov_001_state_udap_evaluated(ctx: CheckContext) -> CheckResult:
    """STATE-COV-001 (coverage, STATE_UDAP, high).
    Trigger: "STATE_UDAP" in A.routing.frameworks.
    Fail: "STATE_UDAP" not in L.frameworks_evaluated AND no finding with
    framework = STATE_UDAP — state law routed but the LLM shows no sign
    of having evaluated it.
    Evidence: targeted states + their statutes, frameworks_evaluated.
    """
    states = _targeted_states(ctx)
    evaluated = ("STATE_UDAP" in ctx.llm.frameworks_evaluated
                 or bool(_state_findings(ctx)))
    if not evaluated:
        return CheckResult(
            check_id="STATE-COV-001", passed=False, severity="high",
            message="asset routes to state UDAP law but the LLM never "
                    "evaluated it",
            evidence={"targeted_states": [_cite(s) for s in states],
                      "frameworks_evaluated": ctx.llm.frameworks_evaluated,
                      "state_table_version": STATE_TABLE_VERSION},
        )
    return CheckResult(
        check_id="STATE-COV-001", passed=True, severity="high",
        message="state UDAP law was evaluated",
        evidence={"targeted_states": [_cite(s) for s in states],
                  "state_udap_findings": [f.finding_id
                                          for f in _state_findings(ctx)]},
    )


@register_check("STATE-COV-002", families=["coverage"],
                frameworks=["STATE_UDAP"])
def state_cov_002_each_state_considered(ctx: CheckContext) -> CheckResult:
    """STATE-COV-002 (coverage, STATE_UDAP, medium).
    Trigger: STATE_UDAP routed AND target_jurisdictions contains state
    codes. States whose table entry has credit_exempt=True are skipped
    when the asset's product_type is a credit product — the exemption is
    cited in the pass evidence.
    Fail: some non-exempt targeted state's code appears in no STATE_UDAP
    finding's reasoning or quoted_evidence — the LLM must have considered
    each state, not "states generally".
    Evidence: unmentioned states + their statutes; exempt-skipped states
    + the exemption note.
    """
    states = _targeted_states(ctx)
    if not states:
        return CheckResult(
            check_id="STATE-COV-002", passed=True, severity="medium",
            message="not triggered: no targeted states",
            evidence={"triggered": False},
        )
    is_credit = ctx.asset.routing.product_type.value in CREDIT_PRODUCTS
    corpus = " ".join((f.reasoning or "") + " " + (f.quoted_evidence or "")
                      for f in _state_findings(ctx))
    skipped, unmentioned, mentioned = [], [], []
    for s in states:
        row = _row(s)
        if is_credit and row["credit_exempt"]:
            skipped.append({"state": s, "statute": row["statute"],
                            "exemption": row["notes"]})
        elif s in corpus:
            mentioned.append(_cite(s))
        else:
            unmentioned.append(_cite(s))
    if unmentioned:
        return CheckResult(
            check_id="STATE-COV-002", passed=False, severity="medium",
            message="targeted states were never individually considered "
                    "in any STATE_UDAP finding",
            evidence={"unmentioned_states": unmentioned,
                      "mentioned_states": mentioned,
                      "exempt_skipped": skipped,
                      "state_table_version": STATE_TABLE_VERSION},
        )
    return CheckResult(
        check_id="STATE-COV-002", passed=True, severity="medium",
        message="every applicable targeted state was considered",
        evidence={"mentioned_states": mentioned, "exempt_skipped": skipped,
                  "state_table_version": STATE_TABLE_VERSION},
    )


@register_check("STATE-SEV-001", families=["severity_sanity"],
                frameworks=["STATE_UDAP"])
def state_sev_001_federal_hit_implies_state_exposure(
        ctx: CheckContext) -> CheckResult:
    """STATE-SEV-001 (severity_sanity, STATE_UDAP, medium).
    Trigger: an adverse FTC finding with severity in {critical, high}
    exists AND a STATE_UDAP finding with verdict = compliant exists.
    Fail: the compliant state finding's reasoning does not name the
    adverse federal finding's finding_id (v1 deterministic proxy for
    "explicit reasoning") — little-FTC acts track the federal standard,
    so a federal deception hit almost always implies state exposure and
    a state-compliant verdict must explicitly engage with it.
    Evidence: federal finding ids, state finding ids, per-state statutes
    for the states the compliant finding covers.
    """
    fed_hits = [f for f in ctx.findings_by_framework.get("FTC", [])
                if f.verdict in ("violation", "potential_violation")
                and f.severity in ("critical", "high")]
    compliant_state = [f for f in _state_findings(ctx)
                       if f.verdict == "compliant"]
    if not fed_hits or not compliant_state:
        return CheckResult(
            check_id="STATE-SEV-001", passed=True, severity="medium",
            message="not triggered: no federal deception hit coexisting "
                    "with a state-compliant verdict",
            evidence={"triggered": False},
        )
    fed_ids = [f.finding_id for f in fed_hits]
    states = _targeted_states(ctx)
    unreconciled = []
    for f in compliant_state:
        if any(fid in (f.reasoning or "") for fid in fed_ids):
            continue
        covered = [s for s in states if s in (f.reasoning or "")] or states
        unreconciled.append({
            "state_finding_id": f.finding_id,
            "states_covered": [_cite(s) for s in covered],
        })
    if unreconciled:
        return CheckResult(
            check_id="STATE-SEV-001", passed=False, severity="medium",
            message="state-compliant verdicts coexist with a critical/high "
                    "federal deception finding without explicitly engaging "
                    "it — little-FTC acts track the federal standard",
            evidence={"federal_finding_ids": fed_ids,
                      "unreconciled_state_findings": unreconciled,
                      "state_table_version": STATE_TABLE_VERSION},
        )
    return CheckResult(
        check_id="STATE-SEV-001", passed=True, severity="medium",
        message="state-compliant verdicts explicitly engage the federal "
                "deception findings",
        evidence={"federal_finding_ids": fed_ids,
                  "state_findings_checked":
                  [f.finding_id for f in compliant_state]},
    )


@register_check("STATE-STR-001", families=["structural"],
                frameworks=["STATE_UDAP"], scope="asset")
def state_str_001_utah_truth_in_advertising(ctx: CheckContext) -> CheckResult:
    """STATE-STR-001 (structural, STATE_UDAP, medium, scope=asset).
    Trigger: "US-UT" in target_jurisdictions AND claim candidates with
    claim_type in {pricing, comparative} exist — Utah's Truth in
    Advertising Act (§ 13-11a) imposes explicit price/availability
    advertising rules (manifest note: rare among states, warrants its
    own rule set).
    Fail: zero segments with role in {disclosure, fine_print, legal} in
    the whole asset — price/comparison claims targeted at Utah with no
    qualifying text anywhere (mirror of FTC5-STR-001's role census,
    applied to pricing/comparative claims under the Utah citation).
    Evidence: triggering claim ids + the Utah statute citation.
    """
    if "US-UT" not in _targeted_states(ctx):
        return CheckResult(
            check_id="STATE-STR-001", passed=True, severity="medium",
            message="not triggered: Utah not targeted",
            evidence={"triggered": False},
        )
    claims = [c for c in ctx.asset.claim_candidates
              if c.claim_type.value in ("pricing", "comparative")]
    if not claims:
        return CheckResult(
            check_id="STATE-STR-001", passed=True, severity="medium",
            message="not triggered: no pricing/comparative claims",
            evidence={"triggered": False, "utah": _cite("US-UT")},
        )
    roles: dict[str, int] = {}
    for s in ctx.asset.segments:
        roles[s.role.value] = roles.get(s.role.value, 0) + 1
    if not any(roles.get(r, 0) for r in ("disclosure", "fine_print", "legal")):
        return CheckResult(
            check_id="STATE-STR-001", passed=False, severity="medium",
            message="pricing/comparison claims targeted at Utah with no "
                    "qualifying disclosure anywhere in the asset (Utah "
                    "Truth in Advertising Act)",
            evidence={"utah": _cite("US-UT"),
                      "trigger_claims": [
                          {"claim_id": c.claim_id,
                           "claim_type": c.claim_type.value,
                           "text": c.text} for c in claims],
                      "segment_role_census": roles,
                      "state_table_version": STATE_TABLE_VERSION},
        )
    return CheckResult(
        check_id="STATE-STR-001", passed=True, severity="medium",
        message="qualifying text exists for Utah-targeted price claims",
        evidence={"utah": _cite("US-UT"),
                  "segment_role_census": roles},
    )

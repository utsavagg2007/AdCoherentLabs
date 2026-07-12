"""MLA checks — §7.1 of docs/check_taxonomy.md (32 CFR Part 232).

The Military Lending Act caps the Military APR for covered borrowers at
36%. The mechanizable slice: when the router attached MLA (military/
servicemember/MAPR wording on a credit ad), a *stated* rate above the
cap is a deterministic, asset-scope defect — no review can change what
the creative says. Covered-borrower status itself is NOT mechanizable.
One function per check_id; docstring = taxonomy row.

Determinism guard (see rule_engine/core.py): stdlib + contracts only.
"""

from __future__ import annotations

from rule_engine.core import CheckContext, CheckResult, register_check
from rule_engine.lexicons import (
    MAPR_CAP,
    THRESHOLDS_VERSION,
    entities_of_type,
    entity_evidence,
)


@register_check("MLA-STR-001", families=["structural"], frameworks=["MLA"],
                scope="asset")
def mla_str_001_stated_rate_above_mapr_cap(ctx: CheckContext) -> CheckResult:
    """MLA-STR-001 (structural, MLA, scope=asset, high).
    Trigger: "MLA" in A.routing.frameworks (military-targeted credit ad).
    Fail: any apr/rate entity with normalized_value > MAPR_CAP (36.0) —
    the creative states a rate above the Military APR cap.
    Evidence: offending entity ids + values, MAPR_CAP + version.
    """
    rates = entities_of_type(ctx, "apr", "rate")
    over_cap = [e for e in rates
                if e.normalized_value is not None
                and e.normalized_value > MAPR_CAP]
    if over_cap:
        return CheckResult(
            check_id="MLA-STR-001", passed=False, severity="high",
            message=f"military-targeted credit ad states a rate above the "
                    f"{MAPR_CAP}% MAPR cap (32 CFR 232.4(b))",
            evidence={"over_cap_entities": entity_evidence(over_cap),
                      "mapr_cap": MAPR_CAP,
                      "thresholds_version": THRESHOLDS_VERSION},
        )
    return CheckResult(
        check_id="MLA-STR-001", passed=True, severity="high",
        message="no stated rate exceeds the MAPR cap"
        if rates else "not triggered: no apr/rate entities",
        evidence={"rates_checked": entity_evidence(rates),
                  "mapr_cap": MAPR_CAP,
                  "thresholds_version": THRESHOLDS_VERSION},
    )

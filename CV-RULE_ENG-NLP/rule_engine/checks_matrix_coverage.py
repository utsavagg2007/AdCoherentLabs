"""Coverage-matrix framework coverage — §7.6 of docs/check_taxonomy.md.

One parameterized check (never N near-copies, mirroring the STATE_UDAP
design): every STRUCTURAL-mechanization framework in the coverage
matrix that the router attached must appear in L.frameworks_evaluated.
Excluded, to keep attribution single-sourced: legacy frameworks with
their own COV-001 (FTC, TILA, Reg_DD, ECOA, FDIC, STATE_UDAP), and
coverage-mechanization frameworks — those are owned by the generated
per-framework checks in checks_coverage_ext (taxonomy §7.7).
ALL-COV-001 is a design companion: it polices the same duty
unattributed. One function per check_id; docstring = taxonomy row.

Determinism guard (see rule_engine/core.py): stdlib + contracts only.
"""

from __future__ import annotations

from rule_engine.core import CheckContext, CheckResult, register_check
from rule_engine.coverage_matrix import (
    COVERAGE_MATRIX,
    COVERAGE_MATRIX_VERSION,
)

#: Frameworks whose coverage is already policed by a dedicated
#: framework-attributed COV-001 check.
_LEGACY_COV = frozenset(
    {"FTC", "TILA", "Reg_DD", "ECOA", "FDIC", "STATE_UDAP"})

#: Matrix frameworks this check polices: every STRUCTURAL row's family
#: value not already covered by a legacy COV-001 (coverage rows are
#: owned by checks_coverage_ext's generated checks). Derived from the
#: versioned matrix constant, so a matrix edit re-scopes the check
#: (and changes the ruleset hash).
MATRIX_COV_FRAMEWORKS = frozenset(
    r["frameworks_enum"] for r in COVERAGE_MATRIX
    if r["mechanization"] == "structural"
    and r["frameworks_enum"] and r["frameworks_enum"] not in _LEGACY_COV
)


@register_check("MATRIX-COV-001", families=["coverage"], frameworks=["*"])
def matrix_cov_001_routed_frameworks_evaluated(ctx: CheckContext) -> CheckResult:
    """MATRIX-COV-001 (coverage, coverage-matrix frameworks, high).
    Trigger: any MATRIX_COV_FRAMEWORKS member in A.routing.frameworks.
    Fail: some such routed framework not in L.frameworks_evaluated —
    the LLM never evaluated a matrix framework the router attached.
    Companion by design: ALL-COV-001 (same duty, unattributed).
    Evidence: missing frameworks, routing signal, matrix version.
    """
    routed = ctx.routed_frameworks & MATRIX_COV_FRAMEWORKS
    if not routed:
        return CheckResult(
            check_id="MATRIX-COV-001", passed=True, severity="high",
            message="not triggered: no matrix frameworks routed",
            evidence={"triggered": False},
        )
    missing = sorted(routed - set(ctx.llm.frameworks_evaluated))
    if missing:
        return CheckResult(
            check_id="MATRIX-COV-001", passed=False, severity="high",
            message="routed coverage-matrix framework(s) never evaluated: "
                    + ", ".join(missing),
            evidence={"missing": missing,
                      "routing_signal": ctx.asset.routing.signal,
                      "frameworks_evaluated": ctx.llm.frameworks_evaluated,
                      "coverage_matrix_version": COVERAGE_MATRIX_VERSION},
        )
    return CheckResult(
        check_id="MATRIX-COV-001", passed=True, severity="high",
        message="all routed matrix frameworks were evaluated",
        evidence={"routed_matrix_frameworks": sorted(routed),
                  "coverage_matrix_version": COVERAGE_MATRIX_VERSION},
    )

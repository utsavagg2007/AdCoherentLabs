"""Generated advisory checks — §7.8 of docs/check_taxonomy.md.

One registered check per advisory-mechanization coverage-matrix row,
GENERATED at import time from the versioned matrix constant (like
checks_coverage_ext). Advisory rows are process/governance rules —
SEC 204-2 / FINRA 4511 + SEA 17a-4 retention, the CFPB CMS expectation,
PCI DSS, the NIST Privacy Framework — that apply to the *advertiser*,
not the creative. Each check emits an informational applicability flag
(scope="advisory", passed=True by construction): retention/program
obligations apply to this material, but nothing about the creative can
satisfy or violate them, so advisories never gate ``EngineReport.passed``
and are never retried. They land in ``EngineReport.advisories``.

Trigger: rows whose routing_trigger names a framework fire when that
framework is routed (SEC 204-2 on SEC-routed material, FINRA 4511 on
FINRA-routed, CFPB CMS on CFPB-routed); rows marked "always ..." are
advertiser-level baselines emitted on every run (PCI DSS, NIST Privacy
Framework).

Determinism guard (see rule_engine/core.py): stdlib + contracts only.
"""

from __future__ import annotations

from rule_engine.core import CheckContext, CheckResult, register_check
from rule_engine.coverage_matrix import (
    ADVISORY_ALWAYS,
    ADVISORY_ON_ROUTED,
    COVERAGE_MATRIX_VERSION,
)

#: check_id of every generated advisory check, sorted (for harnesses).
ADVISORY_CHECK_IDS: tuple[str, ...] = ()


def _make_advisory_check(row: dict, frameworks: list[str]):
    check_id = f"ADV-{row['source']}"

    def advisory_check(ctx: CheckContext) -> CheckResult:
        return CheckResult(
            check_id=check_id, passed=True, severity="low",
            message=(f"{row['citation']} applies to the advertiser's "
                     "compliance program (e.g. retention obligations "
                     "apply to this material); out of creative scope — "
                     "informational applicability flag"),
            evidence={"source": row["source"],
                      "citation": row["citation"],
                      "frameworks_enum": row["frameworks_enum"],
                      "routing_trigger": row["routing_trigger"],
                      "note": row["note"],
                      "coverage_matrix_version": COVERAGE_MATRIX_VERSION},
        )

    advisory_check.__name__ = (
        "advisory_" + row["source"].replace("-", "_"))
    advisory_check.__doc__ = (
        f"{check_id} (advisory, {row['frameworks_enum']}, low).\n"
        f"Trigger: {row['routing_trigger']}.\n"
        "Emits: informational applicability flag (scope=advisory, "
        "passed=True) — never gates, never retries.\n"
        f"Source: {row['citation']}.\n"
        "Generated from coverage_matrix.py at import time (taxonomy §7.8)."
    )
    register_check(check_id, families=["advisory"], frameworks=frameworks,
                   scope="advisory")(advisory_check)
    return check_id


_ids = []
for _fw in sorted(ADVISORY_ON_ROUTED):
    for _row in ADVISORY_ON_ROUTED[_fw]:
        _ids.append(_make_advisory_check(_row, [_fw]))
for _row in sorted(ADVISORY_ALWAYS, key=lambda r: r["source"]):
    _ids.append(_make_advisory_check(_row, ["*"]))
ADVISORY_CHECK_IDS = tuple(sorted(_ids))

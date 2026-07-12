"""Parameterized coverage checks — §7.7 of docs/check_taxonomy.md.

One registered check per coverage-mechanization framework, GENERATED at
import time from the versioned coverage matrix (a constant, so
generation is deterministic and the ruleset hash covers both the matrix
and each generated check). Never N hand-written near-identical files.

Semantics per framework FW (check_id "<FW>-COV-001"):
  * trigger — FW in A.routing.frameworks (registration gates on it);
  * fail    — FW not in L.frameworks_evaluated, OR some finding filed
    under FW is ungrounded per the universal grounding rules (cites a
    segment/entity/claim id that does not resolve). The grounding leg
    re-states ALL-GRD-001/002/003 *attributed to the framework*, so a
    sloppy review of a coverage-class framework is charged to it (the
    universal checks fire alongside by design).

Evidence always carries the framework's matrix rows (source ids +
citations) — the audit-trail payload naming exactly which regulatory
sources the coverage duty derives from.

Determinism guard (see rule_engine/core.py): stdlib + contracts only.
"""

from __future__ import annotations

from rule_engine.core import CheckContext, CheckResult, register_check
from rule_engine.coverage_matrix import (
    COVERAGE_MATRIX,
    COVERAGE_MATRIX_VERSION,
)

#: framework value -> its coverage-mechanization matrix rows.
_ROWS_BY_FRAMEWORK: dict[str, list[dict]] = {}
for _r in COVERAGE_MATRIX:
    if _r["mechanization"] == "coverage" and _r["frameworks_enum"]:
        _ROWS_BY_FRAMEWORK.setdefault(_r["frameworks_enum"], []).append(_r)

#: Every coverage-class framework, sorted for deterministic registration.
COVERAGE_FRAMEWORKS = tuple(sorted(_ROWS_BY_FRAMEWORK))


def _sources_evidence(fw: str) -> list[dict]:
    return [{"source": r["source"], "citation": r["citation"]}
            for r in _ROWS_BY_FRAMEWORK[fw]]


def _make_check(fw: str):
    check_id = f"{fw}-COV-001"

    def coverage_check(ctx: CheckContext) -> CheckResult:
        # Registration gates on the framework, so reaching here means
        # it is routed (the trigger condition holds).
        if fw not in ctx.llm.frameworks_evaluated:
            return CheckResult(
                check_id=check_id, passed=False, severity="high",
                message=f"asset routes to {fw} but the LLM never "
                        "evaluated it",
                evidence={"framework": fw,
                          "matrix_sources": _sources_evidence(fw),
                          "frameworks_evaluated":
                              ctx.llm.frameworks_evaluated,
                          "routing_signal": ctx.asset.routing.signal,
                          "coverage_matrix_version":
                              COVERAGE_MATRIX_VERSION},
            )
        ungrounded = []
        for f in ctx.findings_by_framework.get(fw, []):
            bad_segs = [i for i in f.cited_segment_ids
                        if i not in ctx.segment_by_id]
            bad_ents = [i for i in f.cited_entity_ids
                        if i not in ctx.entity_by_id]
            bad_claim = (f.claim_candidate_id
                         if f.claim_candidate_id
                         and f.claim_candidate_id not in ctx.claim_by_id
                         else None)
            if bad_segs or bad_ents or bad_claim:
                ungrounded.append({"finding_id": f.finding_id,
                                   "unresolved_segment_ids": bad_segs,
                                   "unresolved_entity_ids": bad_ents,
                                   "unresolved_claim_id": bad_claim})
        if ungrounded:
            return CheckResult(
                check_id=check_id, passed=False, severity="high",
                message=f"{fw} findings cite ids that do not resolve — "
                        "the coverage-class review is ungrounded",
                evidence={"framework": fw, "ungrounded": ungrounded,
                          "matrix_sources": _sources_evidence(fw),
                          "coverage_matrix_version":
                              COVERAGE_MATRIX_VERSION},
            )
        return CheckResult(
            check_id=check_id, passed=True, severity="high",
            message=f"{fw} was evaluated and its findings are grounded",
            evidence={"framework": fw,
                      "findings_checked":
                          [f.finding_id for f in
                           ctx.findings_by_framework.get(fw, [])],
                      "coverage_matrix_version": COVERAGE_MATRIX_VERSION},
        )

    coverage_check.__name__ = f"covext_{fw.lower()}_evaluated_and_grounded"
    coverage_check.__doc__ = (
        f"{check_id} (coverage+grounding, {fw}, high).\n"
        f"Trigger: \"{fw}\" in A.routing.frameworks.\n"
        f"Fail: \"{fw}\" not in L.frameworks_evaluated, or a {fw} finding "
        "cites unresolvable ids (framework-attributed restatement of "
        "ALL-GRD-001/002/003, which fire alongside by design).\n"
        "Evidence: matrix source rows + citations, frameworks_evaluated / "
        "unresolved ids.\n"
        "Generated from coverage_matrix.py at import time (taxonomy §7.7)."
    )
    register_check(check_id, families=["coverage", "grounding"],
                   frameworks=[fw])(coverage_check)
    return coverage_check


for _fw in COVERAGE_FRAMEWORKS:
    _make_check(_fw)

"""FTC Endorsement Guides checks — §7.5 of docs/check_taxonomy.md
(16 CFR Part 255, coverage-matrix row ``ftc-endorsement-guides``).

The mechanizable slice: a disclosed endorsement marker (#ad, sponsored,
paid partnership — extracted as endorsement_marker entities) that no
FTC-framework finding addresses and reviewed_clear does not list is a
coverage failure — the endorsement duty was reviewed by nobody. Whether
the endorsement is truthful/typical or the disclosure adequately
conspicuous is NOT mechanizable. One function per check_id;
docstring = taxonomy row.

Determinism guard (see rule_engine/core.py): stdlib + contracts only.
"""

from __future__ import annotations

from rule_engine.core import CheckContext, CheckResult, register_check
from rule_engine.lexicons import entities_of_type, entity_evidence


@register_check("ENDOR-COV-001", families=["coverage"], frameworks=["*"])
def endor_cov_001_marker_addressed_by_ftc(ctx: CheckContext) -> CheckResult:
    """ENDOR-COV-001 (coverage, FTC/Endorsement Guides, high).
    Trigger: endorsement_marker entities present.
    Fail: some marker where no FTC-framework finding cites its entity_id
    or its segment_id, AND its segment_id is not in reviewed_clear — an
    endorsement marker no FTC review addressed.
    Evidence: unaddressed entity ids + raw text, FTC finding ids checked.
    """
    markers = entities_of_type(ctx, "endorsement_marker")
    if not markers:
        return CheckResult(
            check_id="ENDOR-COV-001", passed=True, severity="high",
            message="not triggered: no endorsement markers",
            evidence={"triggered": False},
        )
    ftc_findings = ctx.findings_by_framework.get("FTC", [])
    cited_entities = {i for f in ftc_findings for i in f.cited_entity_ids}
    cited_segments = {i for f in ftc_findings for i in f.cited_segment_ids}
    cleared = set(ctx.llm.reviewed_clear)
    unaddressed = [e for e in markers
                   if e.entity_id not in cited_entities
                   and e.segment_id not in cited_segments
                   and e.segment_id not in cleared]
    if unaddressed:
        return CheckResult(
            check_id="ENDOR-COV-001", passed=False, severity="high",
            message="endorsement marker(s) present but no FTC finding "
                    "addresses them (16 CFR 255 duty reviewed by nobody)",
            evidence={"unaddressed_markers": entity_evidence(unaddressed),
                      "ftc_finding_ids": [f.finding_id for f in ftc_findings]},
        )
    return CheckResult(
        check_id="ENDOR-COV-001", passed=True, severity="high",
        message="every endorsement marker was addressed under FTC",
        evidence={"markers_checked": [e.entity_id for e in markers]},
    )

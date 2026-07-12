"""FCRA / Reg V prescreen checks — §7.2 of docs/check_taxonomy.md
(15 U.S.C. § 1681m(d); 12 CFR Part 1022).

A prescreened firm offer of credit must carry the statutory opt-out
notice. The mechanizable slice: prescreen wording with no opt-out-notice
wording anywhere in the creative is an asset-scope defect. Whether the
offer actually derives from a prescreened list is NOT mechanizable.
One function per check_id; docstring = taxonomy row.

Determinism guard (see rule_engine/core.py): stdlib + contracts only.
"""

from __future__ import annotations

from rule_engine.core import CheckContext, CheckResult, register_check
from rule_engine.lexicons import LEXICON_VERSION, segments_matching


@register_check("FCRAV-STR-001", families=["structural"], frameworks=["*"],
                scope="asset")
def fcrav_str_001_prescreen_needs_optout_notice(ctx: CheckContext) -> CheckResult:
    """FCRAV-STR-001 (structural, FCRA, scope=asset, high).
    Trigger: LEX:PRESCREEN_WORDING matches a segment ("you're
    pre-approved", "firm offer of credit", ...).
    Fail: zero segments match LEX:PRESCREEN_OPTOUT_NOTICE — a prescreen
    solicitation with no 615(d) opt-out notice anywhere in the creative.
    Evidence: prescreen segments + lexemes, lexicon version.
    """
    prescreen = segments_matching(ctx, "PRESCREEN_WORDING")
    if not prescreen:
        return CheckResult(
            check_id="FCRAV-STR-001", passed=True, severity="high",
            message="not triggered: no prescreen wording",
            evidence={"triggered": False},
        )
    notice = segments_matching(ctx, "PRESCREEN_OPTOUT_NOTICE")
    if not notice:
        return CheckResult(
            check_id="FCRAV-STR-001", passed=False, severity="high",
            message="prescreen/firm-offer wording with no FCRA 615(d) "
                    "opt-out notice anywhere in the creative",
            evidence={"prescreen_segments": [
                          {"segment_id": s.segment_id, "matches": m}
                          for s, m in prescreen],
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="FCRAV-STR-001", passed=True, severity="high",
        message="prescreen wording is accompanied by an opt-out notice",
        evidence={"prescreen_segments": [s.segment_id for s, _ in prescreen],
                  "notice_segments": [s.segment_id for s, _ in notice],
                  "lexicon_version": LEXICON_VERSION},
    )

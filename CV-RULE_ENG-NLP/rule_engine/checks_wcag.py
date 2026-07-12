"""WCAG contrast checks — §7.4 of docs/check_taxonomy.md (WCAG 2.x
SC 1.4.3, coverage-matrix row ``wcag-contrast``).

The CV layer already measures text/background contrast per segment
(cv_findings.contrast_ratio). The mechanizable slice: a disclosure-role
segment rendered below the 4.5:1 minimum is an asset-scope defect — the
compliance mouse type is unreadable by the standard's own arithmetic.
Perceptual/context judgments (logotypes, incidental text) are NOT
mechanizable. One function per check_id; docstring = taxonomy row.

Determinism guard (see rule_engine/core.py): stdlib + contracts only.
"""

from __future__ import annotations

from rule_engine.core import CheckContext, CheckResult, register_check
from rule_engine.lexicons import (
    DISCLOSURE_ROLES,
    THRESHOLDS_VERSION,
    WCAG_CONTRAST_MIN,
)


@register_check("WCAG-STR-001", families=["structural"], frameworks=["*"],
                scope="asset")
def wcag_str_001_disclosure_contrast_floor(ctx: CheckContext) -> CheckResult:
    """WCAG-STR-001 (structural, WCAG, scope=asset, medium).
    Trigger: contrast_ratio cv_findings exist for disclosure-role
    segments (disclosure/fine_print/legal).
    Fail: any such measured ratio < WCAG_CONTRAST_MIN (4.5) — the
    disclosure text fails the SC 1.4.3 minimum on the CV layer's own
    measurement.
    Evidence: cv finding ids + values + segment roles, threshold+version.
    """
    role_by_id = {s.segment_id: s.role.value for s in ctx.asset.segments}
    measured = [f for f in ctx.asset.cv_findings
                if f.measurement.value == "contrast_ratio" and f.segment_id
                and role_by_id.get(f.segment_id) in DISCLOSURE_ROLES]
    if not measured:
        return CheckResult(
            check_id="WCAG-STR-001", passed=True, severity="medium",
            message="not triggered: no contrast measurements on "
                    "disclosure-role segments",
            evidence={"triggered": False},
        )
    low = [{"finding_id": f.finding_id, "segment_id": f.segment_id,
            "role": role_by_id[f.segment_id], "contrast_ratio": f.value}
           for f in measured if f.value < WCAG_CONTRAST_MIN]
    if low:
        return CheckResult(
            check_id="WCAG-STR-001", passed=False, severity="medium",
            message=f"disclosure-role text measured below the "
                    f"{WCAG_CONTRAST_MIN}:1 WCAG contrast minimum",
            evidence={"low_contrast": low,
                      "wcag_contrast_min": WCAG_CONTRAST_MIN,
                      "thresholds_version": THRESHOLDS_VERSION},
        )
    return CheckResult(
        check_id="WCAG-STR-001", passed=True, severity="medium",
        message="all measured disclosure-role contrast meets the minimum",
        evidence={"measured": [f.finding_id for f in measured],
                  "wcag_contrast_min": WCAG_CONTRAST_MIN,
                  "thresholds_version": THRESHOLDS_VERSION},
    )

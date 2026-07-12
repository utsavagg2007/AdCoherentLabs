"""CAN-SPAM checks — §7.3 of docs/check_taxonomy.md (16 CFR Part 316).

A commercial email must carry a clear opt-out mechanism. The
mechanizable slice: an asset the router classified as email-structured
(CAN-SPAM routed) that carries neither an optout_marker entity nor any
opt-out wording is an asset-scope defect. Header/sender accuracy and
actual opt-out honoring are NOT mechanizable from the creative.
One function per check_id; docstring = taxonomy row.

Determinism guard (see rule_engine/core.py): stdlib + contracts only.
"""

from __future__ import annotations

from rule_engine.core import CheckContext, CheckResult, register_check
from rule_engine.lexicons import (
    LEXICON_VERSION,
    entities_of_type,
    segments_matching,
)


@register_check("CANSPAM-STR-001", families=["structural"],
                frameworks=["CAN-SPAM"], scope="asset")
def canspam_str_001_email_needs_optout(ctx: CheckContext) -> CheckResult:
    """CANSPAM-STR-001 (structural, CAN-SPAM, scope=asset, medium).
    Trigger: "CAN-SPAM" in A.routing.frameworks (email-structured
    creative per the router's EMAIL_STRUCTURE/optout triggers).
    Fail: zero optout_marker entities AND zero LEX:EMAIL_OPTOUT matches —
    an email creative with no opt-out mechanism at all.
    Evidence: entity census, lexicon version.
    """
    optout_entities = entities_of_type(ctx, "optout_marker")
    optout_wording = segments_matching(ctx, "EMAIL_OPTOUT")
    if not optout_entities and not optout_wording:
        census: dict[str, int] = {}
        for e in ctx.asset.entities:
            census[e.entity_type.value] = census.get(e.entity_type.value, 0) + 1
        return CheckResult(
            check_id="CANSPAM-STR-001", passed=False, severity="medium",
            message="email-structured creative carries no opt-out "
                    "mechanism (no optout_marker entity, no opt-out "
                    "wording)",
            evidence={"entity_type_census": census,
                      "lexicon_version": LEXICON_VERSION},
        )
    return CheckResult(
        check_id="CANSPAM-STR-001", passed=True, severity="medium",
        message="email creative carries an opt-out mechanism",
        evidence={"optout_entities": [e.entity_id for e in optout_entities],
                  "optout_segments": [s.segment_id for s, _ in optout_wording],
                  "lexicon_version": LEXICON_VERSION},
    )

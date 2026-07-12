"""Retry orchestrator: the loop between the engine and the LLM layer.

The deterministic engine (rule_engine.core) never calls the LLM — this
module owns that boundary. It asks the injected LLM layer for a review,
runs the engine's checks, and on failure sends a structured retry
payload back to the LLM layer, at most ``max_rounds`` times in total;
a review that still fails then exits flagged for human review.

Purity note: everything here except the injected ``get_llm_output``
callable is deterministic. The callable is the co-founder's LLM+RAG
layer (network, model calls, nondeterminism live inside it); the engine
run between calls stays pure.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Flat repo: make root importable when run as `python3 rule_engine/orchestrator.py`.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from collections.abc import Callable
from typing import Literal, Optional

from pydantic import BaseModel, Field

from rule_engine import EngineReport, run_checks
from rule_engine.core import CheckResult


class RetryInstruction(BaseModel):
    """One failed check rendered as an actionable instruction for the LLM."""

    check_id: str
    severity: str
    message: str
    instruction: str = Field(
        ..., description="Machine-readable fix directive derived from the "
        "check's evidence; the LLM layer feeds this into its retry prompt.")
    evidence: dict


class RoundRecord(BaseModel):
    """Audit record of one round: the report and the payload sent onward."""

    round: int
    report: EngineReport
    retry_payload: Optional[list[RetryInstruction]] = Field(
        default=None, description="Instructions sent to the LLM after this "
        "round; None when the round passed or the budget was exhausted.")


class FinalResult(BaseModel):
    """Outcome of the evaluate/retry loop with the full audit trail.

    ``status="llm_error"`` means the injected LLM callable raised: the
    loop stopped, every round completed before the failure is preserved
    in ``round_records``, ``llm_error`` carries the exception type and
    message, and ``final_report`` is the last completed round's report
    (None when the very first call failed).
    """

    status: Literal["passed", "human_review", "llm_error"]
    asset_id: str
    rounds: int
    ruleset_version: str
    final_report: Optional[EngineReport] = Field(
        default=None,
        description="Report of the last completed engine round; None only "
        "for status='llm_error' when the round-1 LLM call itself failed.")
    round_records: list[RoundRecord]
    llm_error: Optional[str] = Field(
        default=None,
        description="Set only for status='llm_error': "
        "'<ExceptionType>: <message>' from the get_llm_output call that "
        "failed. The engine never swallows LLM-layer failures silently.")
    advisories: list[CheckResult] = Field(
        default_factory=list,
        description="Advisory applicability flags from the final report "
        "(matrix-generated, scope='advisory'): process/governance "
        "obligations that apply to the advertiser but are out of "
        "creative scope. Informational — they never drive the retry "
        "loop or the status.")


def _instruction(r: CheckResult) -> str:
    """Deterministic fix directive from a failed check's evidence."""
    ev = r.evidence
    claim_ids = ev.get("unaddressed_claim_ids") or ev.get("unreviewed_claim_ids")
    if claim_ids:
        return (f"claims {claim_ids} are unaddressed: evaluate each in a "
                f"finding (claim_candidate_id) or add to reviewed_clear")
    if "missing_frameworks" in ev:
        return (f"frameworks {ev['missing_frameworks']} were routed but not "
                f"evaluated: evaluate them and list them in frameworks_evaluated")
    if "unresolved" in ev or "unresolved_entries" in ev:
        bad = ev.get("unresolved", ev.get("unresolved_entries"))
        return f"remove or correct references to nonexistent ids: {bad}"
    if "unmatched_quotes" in ev:
        ids = [q["finding_id"] for q in ev["unmatched_quotes"]]
        return (f"quoted_evidence in findings {ids} does not appear verbatim "
                f"in the cited segments: re-quote exactly or fix the citations")
    if "unmatched_tokens" in ev:
        ids = sorted({t["finding_id"] for t in ev["unmatched_tokens"]})
        return (f"figures quoted in findings {ids} match no extracted entity "
                f"value: correct the quote or cite the segment as-is")
    if "contradictions" in ev:
        ids = [c["cleared_id"] for c in ev["contradictions"]]
        return (f"ids {ids} are both cleared and cited by adverse findings: "
                f"remove them from reviewed_clear or withdraw the finding")
    if "underrated_findings" in ev:
        ids = [f["finding_id"] for f in ev["underrated_findings"]]
        return (f"severity of findings {ids} is below the deterministic floor "
                f"for this violation class: raise it or change the verdict")
    if "uncited_adverse_findings" in ev:
        ids = [f["finding_id"] for f in ev["uncited_adverse_findings"]]
        return (f"adverse findings {ids} cite nothing: add segment/entity/"
                f"claim citations or withdraw them")
    misfiled = (ev.get("misfiled_findings") or ev.get("orphan_findings")
                or ev.get("conflated_segments") or ev.get("finding_ids"))
    if "-CON-" in r.check_id and misfiled:
        return (f"findings appear filed under the wrong framework "
                f"({misfiled}): refile under the framework the evidence "
                f"actually supports")
    unreviewed = (ev.get("unreviewed_segments") or ev.get("unreviewed_claims")
                  or ev.get("unreviewed_entities"))
    if unreviewed:
        return (f"review the flagged content and either cite it in a finding "
                f"or add it to reviewed_clear: {unreviewed}")
    if "missing_keys" in ev:
        return (f"llm_meta is missing audit keys {ev['missing_keys']}: "
                f"include model and prompt_version")
    return f"resolve and resubmit: {r.message}"


def build_retry_payload(report: EngineReport) -> list[RetryInstruction]:
    """Render a failed report into instructions for the LLM layer's retry."""
    return [RetryInstruction(check_id=r.check_id, severity=r.severity,
                             message=r.message, instruction=_instruction(r),
                             evidence=r.evidence)
            for r in report.failed_checks]


def evaluate_with_retry(
    asset: dict,
    get_llm_output: Callable[[dict, EngineReport | None], dict],
    max_rounds: int = 2,
    *,
    ruleset_version: str | None = None,
) -> FinalResult:
    """Run the review/check/retry loop, at most ``max_rounds`` LLM rounds.

    Round 1 calls ``get_llm_output(asset, None)``; each retry passes the
    failed EngineReport (the LLM layer can render it via
    ``build_retry_payload``). Returns as soon as a round passes; after
    ``max_rounds`` without passing, exits with status "human_review".
    The FinalResult carries every round's report and the payload sent
    after it — the complete audit trail.

    Only review-scope failures drive the loop: ``EngineReport.passed``
    and ``failed_checks`` exclude asset-scope defects, which no re-review
    can fix. Asset defects ride along in every round's report
    (``asset_defects``) for downstream consumers — "passed" means the
    review is sound, not that the ad is clean.

    If ``get_llm_output`` itself raises (network, timeout, provider
    error), the loop stops and returns ``status="llm_error"`` with the
    exception type+message in ``llm_error`` and every completed round
    preserved in ``round_records`` — the failure is surfaced, never
    swallowed, and the audit trail is never lost.
    """
    if max_rounds < 1:
        raise ValueError("max_rounds must be >= 1")
    from rule_engine.version import RULESET_VERSION
    ruleset_version = ruleset_version or RULESET_VERSION

    records: list[RoundRecord] = []
    report: EngineReport | None = None
    for round_no in range(1, max_rounds + 1):
        try:
            llm_output = get_llm_output(asset, report)
        except Exception as exc:  # noqa: BLE001 — LLM/transport failure
            # The LLM layer failed (network, timeout, provider error, a
            # bug). Do not lose the audit trail: every completed round
            # stays in round_records, and the failure is surfaced
            # loudly via status + llm_error — never swallowed.
            return FinalResult(
                status="llm_error",
                asset_id=(report.asset_id if report is not None
                          else str(asset.get("asset_id", "unknown"))),
                rounds=len(records),
                ruleset_version=ruleset_version,
                final_report=report,
                round_records=records,
                llm_error=f"{type(exc).__name__}: {exc}",
                advisories=report.advisories if report is not None else [],
            )
        report = run_checks(asset, llm_output, ruleset_version=ruleset_version)
        if report.passed:
            records.append(RoundRecord(round=round_no, report=report))
            return FinalResult(status="passed", asset_id=report.asset_id,
                               rounds=round_no, ruleset_version=ruleset_version,
                               final_report=report, round_records=records,
                               advisories=report.advisories)
        payload = (build_retry_payload(report)
                   if round_no < max_rounds else None)
        records.append(RoundRecord(round=round_no, report=report,
                                   retry_payload=payload))
    return FinalResult(status="human_review", asset_id=report.asset_id,
                       rounds=max_rounds, ruleset_version=ruleset_version,
                       final_report=report, round_records=records,
                       advisories=report.advisories)


if __name__ == "__main__":
    import copy
    import json

    root = Path(_REPO_ROOT)

    def show(title: str, res: FinalResult) -> None:
        print(f"\n=== {title} ===")
        print(f"status={res.status}  asset={res.asset_id}  rounds={res.rounds}"
              f"  ruleset={res.ruleset_version}")
        for rec in res.round_records:
            rep = rec.report
            print(f"  round {rec.round}: "
                  f"{'PASS' if rep.passed else 'FAIL'} "
                  f"({len(rep.results)} checks, "
                  f"{len(rep.failed_checks)} review failures, "
                  f"{len(rep.asset_defects)} asset defects)")
            for f in rep.failed_checks:
                print(f"    - {f.check_id} [{f.severity}] {f.message}")
            for f in rep.asset_defects:
                print(f"    ~ asset defect: {f.check_id} [{f.severity}] "
                      f"{f.message}")
        for a in res.advisories:
            print(f"  i advisory: {a.check_id} — {a.message[:100]}")
            if rec.retry_payload is not None:
                print(f"    retry payload sent to LLM layer:")
                for ins in rec.retry_payload:
                    print(f"      * {ins.check_id}: {ins.instruction[:150]}")

    # --- Path 1: a clean pair passes in round 1 -------------------------
    clean_asset = {
        "asset_id": "demo_clean",
        "segments": [{"segment_id": "seg_1", "role": "body", "source": "text",
                      "text": "Five budgeting tips for the new year"}],
        "routing": {"product_type": "unknown", "frameworks": ["FTC"],
                    "signal": "demo: generic content -> FTC baseline"},
        "provenance": {"cv_version": "demo", "nlp_version": "demo",
                       "ruleset_hash": "demo",
                       "timestamp": "2026-07-07T00:00:00Z"},
    }
    clean_output = {
        "asset_id": "demo_clean",
        "findings": [],
        "reviewed_clear": ["seg_1"],
        "frameworks_evaluated": ["FTC"],
        "llm_meta": {"model": "stub", "prompt_version": "demo-v0"},
    }
    calls = {"n": 0}

    def stub_clean(asset: dict, prior: EngineReport | None) -> dict:
        calls["n"] += 1
        return copy.deepcopy(clean_output)

    res1 = evaluate_with_retry(clean_asset, stub_clean,
                               ruleset_version="taxonomy-v1")
    show("Path 1: clean pair", res1)
    assert res1.status == "passed" and res1.rounds == 1 and calls["n"] == 1

    # --- Path 2: a corrupted output the stub never fixes ----------------
    gold = json.loads(
        (root / "data" / "gold" / "881224884306098.json").read_text())
    corrupted = json.loads(
        (root / "data" / "llm_outputs" / "sample_output.json").read_text())
    del corrupted["findings"][0]["claim_candidate_id"]   # clm_3 unaddressed
    corrupted["findings"][2]["cited_segment_ids"].append("seg_999")
    calls["n"] = 0

    def stub_stubborn(asset: dict, prior: EngineReport | None) -> dict:
        calls["n"] += 1
        return copy.deepcopy(corrupted)  # ignores the retry payload

    res2 = evaluate_with_retry(gold, stub_stubborn, max_rounds=2,
                               ruleset_version="taxonomy-v1")
    show("Path 2: stubborn corrupted output", res2)
    assert res2.status == "human_review" and res2.rounds == 2
    assert calls["n"] == 2 and len(res2.round_records) == 2
    print(f"\nLLM layer was called exactly {calls['n']} times; "
          f"both paths behaved as specified.")

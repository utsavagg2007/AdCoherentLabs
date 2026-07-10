"""Deterministic rule-engine core: check registry, context, and runner.

=============================================================================
DETERMINISM INVARIANT — DO NOT WEAKEN
This module, and every check module that registers into it, must stay pure
Python: zero model calls, zero network calls, zero nondeterministic inputs
at check time. The only permitted imports are the standard library and the
two pydantic contract modules (``schema``, ``llm_contract``). Regulatory
vocabulary and thresholds are compiled in as versioned constants (see
docs/check_taxonomy.md appendices) — never fetched, never inferred. The one
tolerated nondeterminism is ``EngineReport.timestamp``.
=============================================================================

The engine consumes the two JSON contracts — ``schema.AssetRepresentation``
and ``llm_contract.LLMOutput`` — and emits pass or a structured failure
report. It never calls the LLM; the retry loop (max 2 rounds, then
human-review flag) lives in the orchestrator module, not here.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Flat repo: make root importable when run as `python3 rule_engine/core.py`.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field

from llm_contract import LLMFinding, LLMOutput, Severity
from schema import AssetRepresentation

from rule_engine.version import RULESET_VERSION, ruleset_hash

#: Check families, as defined in docs/check_taxonomy.md.
FAMILIES = frozenset(
    {"coverage", "grounding", "consistency", "structural", "severity_sanity"}
)


Scope = Literal["review", "asset"]


class CheckResult(BaseModel):
    """Outcome of one check against one asset/output pair."""

    check_id: str = Field(..., min_length=1)
    passed: bool
    evidence: dict = Field(
        default_factory=dict,
        description="Ids, values, and thresholds backing the outcome — the "
        "audit trail the orchestrator sends back to the LLM on retry.",
    )
    message: str = Field(..., min_length=1)
    severity: Severity = Field(
        ...,
        description="Weight of a failure of this check (taxonomy column); "
        "recorded on passes too so reports are self-describing.",
    )
    scope: Scope = Field(
        default="review",
        description="Stamped from the registration: 'review' failures are "
        "the LLM's to fix on retry; 'asset' failures are true statements "
        "about the ad that no re-review can change.",
    )


class CheckContext:
    """Parsed inputs plus lookups built once and shared by every check.

    Attributes:
        asset: validated AssetRepresentation.
        llm: validated LLMOutput.
        segment_by_id / entity_by_id / claim_by_id: id -> model.
        routed_frameworks: framework values in asset.routing.frameworks.
        findings_by_framework: framework value -> findings issued under it.
        addressed_claim_ids: cited claim_candidate_ids ∪ reviewed_clear
            (reviewed_clear may also hold segment ids; membership tests on
            claim ids are unaffected).
    """

    def __init__(self, asset: AssetRepresentation, llm: LLMOutput) -> None:
        self.asset = asset
        self.llm = llm
        self.segment_by_id = {s.segment_id: s for s in asset.segments}
        self.entity_by_id = {e.entity_id: e for e in asset.entities}
        self.claim_by_id = {c.claim_id: c for c in asset.claim_candidates}
        self.routed_frameworks = frozenset(f.value for f in asset.routing.frameworks)
        self.findings_by_framework: dict[str, list[LLMFinding]] = {}
        for finding in llm.findings:
            self.findings_by_framework.setdefault(finding.framework.value, []).append(finding)
        self.addressed_claim_ids = frozenset(
            f.claim_candidate_id for f in llm.findings if f.claim_candidate_id
        ) | frozenset(llm.reviewed_clear)


class RegisteredCheck(NamedTuple):
    check_id: str
    fn: Callable[[CheckContext], CheckResult]
    families: tuple[str, ...]
    frameworks: tuple[str, ...]
    scope: str


#: Global registry, keyed by check_id. Populated via @register_check.
CHECK_REGISTRY: dict[str, RegisteredCheck] = {}


def register_check(check_id: str, families: list[str], frameworks: list[str],
                   scope: str = "review"):
    """Register a ``(ctx) -> CheckResult`` function under ``check_id``.

    ``frameworks=["*"]`` marks a universal check that runs on every asset;
    otherwise the check runs only when one of its framework values appears
    in ``asset.routing.frameworks`` (compared verbatim, e.g. "Reg_DD").

    ``scope`` splits the verdict: "review" (default) checks judge the LLM
    output and gate ``EngineReport.passed``; "asset" checks are decidable
    from the asset alone — their failures are reported as
    ``asset_defects``, never retried, and do not fail the review.
    """
    if not check_id:
        raise ValueError("check_id must be non-empty")
    unknown = set(families) - FAMILIES
    if not families or unknown:
        raise ValueError(f"families must be non-empty and within {sorted(FAMILIES)}; "
                         f"got unknown {sorted(unknown)}")
    if not frameworks:
        raise ValueError("frameworks must be non-empty (use ['*'] for universal)")
    if scope not in ("review", "asset"):
        raise ValueError(f"scope must be 'review' or 'asset', got {scope!r}")
    if check_id in CHECK_REGISTRY:
        raise ValueError(f"duplicate check_id {check_id!r}")

    def decorator(fn: Callable[[CheckContext], CheckResult]):
        CHECK_REGISTRY[check_id] = RegisteredCheck(
            check_id, fn, tuple(families), tuple(frameworks), scope
        )
        return fn

    return decorator


class EngineReport(BaseModel):
    """Verdict of one engine run, split by scope.

    ``passed`` answers "did the LLM do its job?" — it is true iff no
    review-scope check failed. ``failed_checks`` holds those review-scope
    failures (the orchestrator's retry payload source). ``asset_defects``
    holds asset-scope failures: deterministic true statements about the
    ad itself (missing disclosures, prominence floors) that no re-review
    can change — they never gate ``passed`` and are never retried, but
    they are part of the verdict downstream consumers act on.
    """

    asset_id: str
    passed: bool
    results: list[CheckResult]
    failed_checks: list[CheckResult]
    asset_defects: list[CheckResult] = []
    ruleset_version: str
    ruleset_hash: str = Field(
        default="",
        description="Content hash of the registry that ran (check ids + "
        "source + lexicons + thresholds); see rule_engine/version.py.",
    )
    timestamp: datetime


def run_checks(asset: dict | AssetRepresentation, llm_output: dict | LLMOutput,
               ruleset_version: str | None = None) -> EngineReport:
    """Run every applicable registered check and report.

    Inputs that arrive as dicts are validated against their contracts;
    contract violations raise (that is upstream breakage, not a finding).
    Checks run in sorted check_id order for reproducible reports. A check
    that raises, or that returns a result under the wrong check_id, is
    reported as a high-severity failure rather than aborting the run.
    ``ruleset_version`` defaults to rule_engine.version.RULESET_VERSION;
    the report is additionally stamped with the registry content hash.
    """
    asset_model = (AssetRepresentation.model_validate(asset)
                   if isinstance(asset, dict) else asset)
    llm_model = (LLMOutput.model_validate(llm_output)
                 if isinstance(llm_output, dict) else llm_output)
    ctx = CheckContext(asset_model, llm_model)

    results: list[CheckResult] = []
    for check in sorted(CHECK_REGISTRY.values()):
        if "*" not in check.frameworks and not (
            set(check.frameworks) & ctx.routed_frameworks
        ):
            continue
        try:
            result = check.fn(ctx)
            if result.check_id != check.check_id:
                raise RuntimeError(
                    f"check returned result for {result.check_id!r}"
                )
        except Exception as exc:  # a buggy check must not silently pass
            result = CheckResult(
                check_id=check.check_id,
                passed=False,
                severity="high",
                message=f"check crashed: {type(exc).__name__}: {exc}",
                evidence={"exception": repr(exc)},
            )
        # Registration is the source of truth for scope.
        results.append(result.model_copy(update={"scope": check.scope}))

    review_failures = [r for r in results if not r.passed and r.scope == "review"]
    asset_defects = [r for r in results if not r.passed and r.scope == "asset"]
    return EngineReport(
        asset_id=asset_model.asset_id,
        passed=not review_failures,
        results=results,
        failed_checks=review_failures,
        asset_defects=asset_defects,
        ruleset_version=ruleset_version or RULESET_VERSION,
        ruleset_hash=ruleset_hash(CHECK_REGISTRY),
        timestamp=datetime.now(timezone.utc),
    )


if __name__ == "__main__":
    import json

    @register_check("DEMO-CON-001", families=["consistency"], frameworks=["*"])
    def _demo_asset_id_match(ctx: CheckContext) -> CheckResult:
        ok = ctx.llm.asset_id == ctx.asset.asset_id
        return CheckResult(
            check_id="DEMO-CON-001", passed=ok, severity="critical",
            message="LLM output and asset agree on asset_id" if ok
            else "LLM output reviews a different asset",
            evidence={"asset.asset_id": ctx.asset.asset_id,
                      "llm.asset_id": ctx.llm.asset_id},
        )

    @register_check("DEMO-COV-002", families=["coverage"], frameworks=["TILA"])
    def _demo_tila_evaluated(ctx: CheckContext) -> CheckResult:
        ok = "TILA" in ctx.llm.frameworks_evaluated
        return CheckResult(
            check_id="DEMO-COV-002", passed=ok, severity="high",
            message="TILA was evaluated" if ok
            else "asset routes to TILA but the LLM never evaluated it",
            evidence={"routed": sorted(ctx.routed_frameworks),
                      "frameworks_evaluated": ctx.llm.frameworks_evaluated},
        )

    root = Path(_REPO_ROOT)
    llm_output = json.loads(
        (root / "data" / "llm_outputs" / "sample_output.json").read_text()
    )
    # Pair with the gold asset the sample reviews; else any gold asset.
    gold = root / "data" / "gold" / f"{llm_output['asset_id']}.json"
    if not gold.exists():
        gold = sorted((root / "data" / "gold").glob("*.json"))[0]
    asset = json.loads(gold.read_text())

    report = run_checks(asset, llm_output, ruleset_version="demo-v0")
    print(f"asset {report.asset_id} vs {gold.name}: "
          f"{'PASS' if report.passed else 'FAIL'} "
          f"({len(report.results)} checks, {len(report.failed_checks)} failed)")
    print(report.model_dump_json(indent=2))

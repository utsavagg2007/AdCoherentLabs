"""Offline wiring proof for the connected four-layer engine.

Runs the REAL Layers 1, 2 and 4 (CV/NLP pipeline and rule engine) with a
deterministic stub standing in for the Layer-3 LLM provider and a stub
regulation retriever — no network, no database, no API keys. Proves:

  A. adapter unit behavior (verdict remap, framework coercion,
     jurisdiction union, OCR tier map);
  B. clean path — a sound review passes in round 1;
  C. callback path — an incomplete review fails deterministic checks,
     the rule engine calls the LLM back WITH fix instructions in the
     prompt, round 2 passes;
  D. human-interference path — a stubborn LLM burns 1 initial + 2
     callbacks, the run exits status=human_review with instructions,
     and resume_with_human_guidance (operator prompt in the LLM prompt)
     produces a verified pass;
  E. llm-error path — a provider crash surfaces as status=llm_error.

Run:  python -m engine.selftest
"""

from __future__ import annotations

import json
import sys
from datetime import date
from typing import Any

from . import _paths  # noqa: F401  (sys.path bootstrap - must be first)

from adcoherent_rag.models import RetrievalResult
from adcoherent_rag.review.providers import CompletionResult

from .adapter import adapt_review_for_rule_engine, coerce_framework
from .llm_layer import retrieval_jurisdictions
from .orchestrator import (
    prepare_asset,
    resume_with_human_guidance,
    review_and_verify,
)
from .tiers import PRODUCT_TIERS, ocr_tier_for

AD_TEXT = "Get 5.99% APR, guaranteed approval!"

ASSET_MARKER = "# Ad asset under review (NLP layer output)"
FEEDBACK_MARKER = "# Reviewer feedback on your previous review"
GUIDANCE_MARKER = "OPERATOR GUIDANCE"


def _extract_asset(user_prompt: str) -> dict:
    """Parse the asset JSON embedded in the review prompt (stub-side)."""
    _, _, tail = user_prompt.partition(ASSET_MARKER)
    body = tail.strip()
    end = body.find("\n\n# ")
    return json.loads(body if end < 0 else body[:end])


def _clear_review(asset: dict) -> dict:
    """A complete, grounded 'everything reviewed, nothing adverse' review.

    reviewed_clear carries claim + segment ids only (entity ids are not
    valid there — ALL-GRD-005). When the ad targets states, STATE-COV-002
    requires each state to be individually considered in a STATE_UDAP
    finding, so a compliant one is emitted naming every targeted state.
    """
    cleared = ([c["claim_id"] for c in asset.get("claim_candidates", [])]
               + [s["segment_id"] for s in asset.get("segments", [])])
    frameworks = list((asset.get("routing") or {}).get("frameworks", []))
    findings: list[dict] = []
    states = [j for j in asset.get("target_jurisdictions", []) if "-" in str(j)]
    if "STATE_UDAP" in frameworks and states:
        seg = asset["segments"][0]
        quote = "guaranteed approval"  # digit-free verbatim fragment
        findings.append({
            "finding_id": "llmf_state_001",
            "framework": "STATE_UDAP",
            "severity": "low",
            "verdict": "compliant",
            "cited_segment_ids": [seg["segment_id"]],
            "cited_entity_ids": [],
            "quoted_evidence": quote if quote in seg["text"] else seg["text"][:24],
            "claim_candidate_id": None,
            "regulation_citations": ["Cal. Bus. & Prof. Code § 17500 (stub)"],
            "reasoning": ("Considered each targeted state individually: "
                          + ", ".join(states)
                          + ". No state-specific deceptive-practice exposure "
                            "beyond the federal analysis on this record."),
            "scope_of_improvement": "No change required.",
        })
    return {
        "findings": findings,
        "reviewed_clear": cleared,
        "frameworks_evaluated": frameworks,
    }


def _incomplete_review(asset: dict) -> dict:
    """Leaves every claim candidate unaddressed -> coverage check fails."""
    doc = _clear_review(asset)
    claim_ids = {c["claim_id"] for c in asset.get("claim_candidates", [])}
    doc["reviewed_clear"] = [i for i in doc["reviewed_clear"] if i not in claim_ids]
    return doc


class StubProvider:
    """Deterministic Layer-3 stand-in.

    mode="honest"    incomplete first, then obeys rule-engine feedback
    mode="stubborn"  ignores feedback; obeys only operator guidance
    mode="crash"     raises (provider outage)
    """

    def __init__(self, mode: str = "honest"):
        self.mode = mode
        self.prompts: list[str] = []

    def complete(self, tier: Any, system: str, user: str) -> CompletionResult:
        if self.mode == "crash":
            raise RuntimeError("stub provider outage")
        self.prompts.append(user)
        asset = _extract_asset(user)
        saw_feedback = FEEDBACK_MARKER in user
        saw_guidance = GUIDANCE_MARKER in user
        if self.mode == "honest":
            payload = _clear_review(asset) if saw_feedback else _incomplete_review(asset)
        else:  # stubborn: only a human gets through
            payload = _clear_review(asset) if saw_guidance else _incomplete_review(asset)
        return CompletionResult(payload=payload, model="stub-compliance-llm",
                                input_tokens=0, output_tokens=0)


def stub_retriever(conn, embedder, query, *, k, frameworks, jurisdictions, as_of):
    """One deterministic regulation chunk per (framework, query)."""
    fw = (frameworks or ["GEN"])[0]
    return [RetrievalResult(
        chunk_id=f"stub-{fw}-{abs(hash(query)) % 9999}",
        version_id=f"ver-stub-{fw}",
        source_id="stub-source",
        citation="12 CFR § 0.0 (stub)",
        heading="Stub advertising rule",
        subsection_label="(a)",
        context_header=f"12 CFR § 0.0 — Stub advertising rule [{fw}]",
        text="An advertisement shall not be misleading. (stub text)",
        score=1.0, vector_rank=1, lexical_rank=1,
        effective_start=date(2024, 1, 1), effective_end=None, metadata={},
    )]


def main() -> int:
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        status = "PASS" if cond else "FAIL"
        print(f"  [{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
        if not cond:
            failures.append(name)

    print("== A. adapter / tier-map units ==")
    fake = {
        "asset_id": "x", "reviewed_clear": [],
        "frameworks_evaluated": ["Reg DD", "reg_dd", "FTC"],
        "findings": [
            {"finding_id": "f1", "framework": "Reg DD", "severity": "medium",
             "verdict": "needs_review", "cited_segment_ids": [],
             "cited_entity_ids": [], "quoted_evidence": "q",
             "claim_candidate_id": None, "regulation_citations": [],
             "reasoning": "r", "scope_of_improvement": "s"},
            {"finding_id": "f2", "framework": "NOT_A_FRAMEWORK",
             "severity": "low", "verdict": "compliant",
             "cited_segment_ids": [], "cited_entity_ids": [],
             "quoted_evidence": "q", "claim_candidate_id": None,
             "regulation_citations": [], "reasoning": "r",
             "scope_of_improvement": "s"},
        ],
        "llm_meta": {"model": "m", "prompt_version": "v"},
    }
    adapted = adapt_review_for_rule_engine(fake)
    check("needs_review -> potential_violation",
          adapted["findings"][0]["verdict"] == "potential_violation")
    check("framework 'Reg DD' coerced to enum value",
          adapted["findings"][0]["framework"] == "Reg_DD")
    check("unknown-framework finding dropped (recorded in notes)",
          len(adapted["findings"]) == 1 and any(
              n["action"] == "dropped_unknown_framework" for n in adapted["adapter_notes"]))
    check("frameworks_evaluated coerced + deduped",
          adapted["frameworks_evaluated"] == ["Reg_DD", "FTC"])
    check("original document untouched",
          fake["findings"][0]["verdict"] == "needs_review")
    check("coerce_framework('CAN_SPAM') hits 'CAN-SPAM' enum value",
          coerce_framework("CAN_SPAM") == "CAN-SPAM")
    check("state targeting unions federal 'US'",
          retrieval_jurisdictions(["US-CA"]) == ["US", "US-CA"])
    check("PaddleOCR (local) OCR tier on every product tier",
          all(ocr_tier_for(t) == "free" for t in PRODUCT_TIERS))

    print("== layers 1+2: prepare_asset over the sample ad ==")
    asset = prepare_asset(asset_id="selftest_ad", text=AD_TEXT,
                          product_tier="pro", target_jurisdictions=["US-CA"])
    frameworks = (asset.get("routing") or {}).get("frameworks", [])
    check("NLP routed at least one framework", bool(frameworks),
          f"routing={asset.get('routing')}")
    check("NLP extracted claim candidates",
          bool(asset.get("claim_candidates")),
          f"claims={asset.get('claim_candidates')}")
    print(f"  routed frameworks: {frameworks}; "
          f"claims: {[c['claim_id'] for c in asset['claim_candidates']]}")

    print("== B. clean path: sound review passes round 1 ==")
    honest_after_pass = StubProvider(mode="honest")
    # make round 1 already complete: honest stub with no prior feedback is
    # incomplete by design, so use a dedicated always-clear provider here
    class ClearProvider(StubProvider):
        def complete(self, tier, system, user):
            self.prompts.append(user)
            return CompletionResult(payload=_clear_review(_extract_asset(user)),
                                    model="stub-compliance-llm")
    clear = ClearProvider()
    res_b = review_and_verify(asset, "pro", provider=clear,
                              retriever=stub_retriever)
    check("status=passed", res_b.status == "passed", res_b.status)
    check("exactly 1 LLM round used", res_b.llm_rounds_used == 1)
    check("verification says review sound",
          bool(res_b.verification and res_b.verification.review_passed))
    check("regulation excerpts reached the prompt",
          "12 CFR § 0.0" in clear.prompts[0])
    check("final llm_review is the product-format document",
          res_b.llm_review is not None
          and set(res_b.llm_review) >= {"asset_id", "findings", "reviewed_clear",
                                        "frameworks_evaluated", "llm_meta"})

    print("== C. callback path: rule engine calls the LLM back with instructions ==")
    honest = StubProvider(mode="honest")
    res_c = review_and_verify(asset, "pro", provider=honest,
                              retriever=stub_retriever)
    check("status=passed after callback", res_c.status == "passed", res_c.status)
    check("2 LLM rounds used (1 initial + 1 callback)",
          res_c.llm_rounds_used == 2, f"used={res_c.llm_rounds_used}")
    check("round 1 failed deterministic checks",
          res_c.rounds[0].rule_engine_passed is False)
    check("round 2 was a rule-engine callback",
          res_c.rounds[1].was_rule_engine_callback)
    check("fix instructions reached the round-2 prompt",
          len(honest.prompts) == 2 and FEEDBACK_MARKER in honest.prompts[1]
          and "unaddressed" in honest.prompts[1])
    check("round-2 feedback recorded in the audit trail",
          bool(res_c.rounds[1].feedback_sent_to_llm))

    print("== D. human-interference path: budget exhausted, operator resumes ==")
    stubborn = StubProvider(mode="stubborn")
    res_d = review_and_verify(asset, "pro", provider=stubborn,
                              retriever=stub_retriever)
    check("status=human_review", res_d.status == "human_review", res_d.status)
    check("exactly 3 LLM rounds (1 initial + 2 callbacks)",
          res_d.llm_rounds_used == 3, f"used={res_d.llm_rounds_used}")
    check("human_review request carries instructions",
          bool(res_d.human_review and res_d.human_review.instructions))
    res_d2 = resume_with_human_guidance(
        asset,
        "Claims clm_* were verified against the retrieved excerpts by the "
        "operator; evaluate each claim candidate explicitly and clear the "
        "ones with adequate disclosure.",
        product_tier="pro", previous=res_d,
        provider=stubborn, retriever=stub_retriever)
    check("resume: status=passed", res_d2.status == "passed", res_d2.status)
    check("resume linked to the exhausted run",
          res_d2.resumed_from_run_id == res_d.run_id)
    check("operator guidance reached the prompt",
          GUIDANCE_MARKER in stubborn.prompts[-1])
    check("resume round flagged had_human_guidance",
          res_d2.rounds[0].had_human_guidance)

    print("== E. llm-error path: provider outage surfaces, never swallowed ==")
    res_e = review_and_verify(asset, "pro", provider=StubProvider(mode="crash"),
                              retriever=stub_retriever)
    check("status=llm_error", res_e.status == "llm_error", res_e.status)
    check("error message preserved",
          bool(res_e.llm_error and "stub provider outage" in res_e.llm_error))

    print()
    if failures:
        print(f"SELFTEST FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("SELFTEST PASSED: all four layers wired - CV/NLP -> RAG+LLM -> "
          "rule engine, callback loop (1+2) and human-interference path verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

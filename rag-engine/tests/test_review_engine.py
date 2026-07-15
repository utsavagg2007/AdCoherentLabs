"""LLM review layer: tiers, context building, schema, engine assembly.

No DB and no provider SDKs required — the retriever and provider are
injected fakes.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from adcoherent_rag.models import RetrievalResult
from adcoherent_rag.review.context import (
    ReviewContext,
    build_context,
    build_queries,
    corpus_framework_for,
)
from adcoherent_rag.review.engine import ReviewError, review_asset
from adcoherent_rag.review.prompts import build_user_prompt, format_excerpts
from adcoherent_rag.review.providers import CompletionResult
from adcoherent_rag.review.schema import SchemaError, validate_llm_output
from adcoherent_rag.review.tiers import TIERS, get_tier

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixtures

def _nlp_result() -> dict:
    template = PROJECT_ROOT.parent / "nlp-result-template.json"
    if template.exists():
        return json.loads(template.read_text())
    # Minimal equivalent if the template file moves.
    return {
        "asset_id": "asset_0001",
        "segments": [
            {"segment_id": "seg_1", "text": "Earn 4.50% APY on every dollar",
             "role": "headline"},
            {"segment_id": "seg_2",
             "text": "APY accurate as of 06/01/2026. Member FDIC.",
             "role": "disclosure"},
        ],
        "entities": [{"entity_id": "ent_1", "raw_text": "4.50% APY",
                      "segment_id": "seg_1"}],
        "claim_candidates": [{"claim_id": "clm_1", "claim_type": "pricing",
                              "text": "Earn 4.50% APY on every dollar",
                              "segment_id": "seg_1"}],
        "cv_findings": [],
        "routing": {"product_type": "deposit_account",
                    "frameworks": ["Reg_DD", "FTC"],
                    "signal": "APY rate in headline"},
    }


def _chunk(chunk_id: str, framework_citation: str = "12 CFR § 1030.8") -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        version_id=f"ver_{chunk_id}",
        source_id="cfpb-reg-dd-tisa",
        citation=framework_citation,
        heading="Advertising",
        subsection_label="(a)",
        context_header=f"{framework_citation} — Advertising — (a)",
        text="An advertisement shall not be misleading or inaccurate...",
        score=0.05,
        vector_rank=1,
        lexical_rank=1,
        effective_start=date(2024, 1, 1),
        effective_end=None,
        metadata={},
    )


def _fake_retriever(chunks_per_call: int = 2):
    calls: list[dict] = []

    def retriever(conn, embedder, query, *, k, frameworks, jurisdictions, as_of):
        calls.append({"query": query, "k": k, "frameworks": frameworks,
                      "jurisdictions": jurisdictions, "as_of": as_of})
        fw = (frameworks or ["X"])[0]
        return [_chunk(f"{fw}-{query[:12]}-{i}") for i in range(chunks_per_call)]

    retriever.calls = calls  # type: ignore[attr-defined]
    return retriever


def _llm_payload(**overrides) -> dict:
    finding = {
        "finding_id": "llmf_001",
        "framework": "Reg_DD",
        "severity": "medium",
        "verdict": "potential_violation",
        "cited_segment_ids": ["seg_1"],
        "cited_entity_ids": ["ent_1"],
        "quoted_evidence": "Earn 4.50% APY on every dollar",
        "claim_candidate_id": "clm_1",
        "regulation_citations": ["12 CFR § 1030.8"],
        "reasoning": "APY stated without required qualifying disclosures nearby.",
        "scope_of_improvement": "Place the 'accurate as of' date and rate-change "
                                "language adjacent to the headline APY.",
    }
    payload = {
        "findings": [finding],
        "reviewed_clear": ["seg_2"],
        "frameworks_evaluated": ["Reg_DD", "FTC"],
    }
    payload.update(overrides)
    return payload


class FakeProvider:
    def __init__(self, payload: dict, model: str = "fake-model"):
        self.payload = payload
        self.model = model
        self.seen: list[tuple] = []

    def complete(self, tier, system, user):
        self.seen.append((tier, system, user))
        return CompletionResult(payload=json.loads(json.dumps(self.payload)),
                                model=self.model, input_tokens=100, output_tokens=50)


# ---------------------------------------------------------------------------
# Tiers

def test_tier_registry_matches_product_spec():
    assert get_tier("free").provider == "openrouter"
    assert get_tier("free").model == "qwen/qwen3.7-plus"
    assert get_tier("hobby").provider == "openrouter"
    assert get_tier("hobby").model == "qwen/qwen3.7-max"
    assert get_tier("pro").model == "claude-sonnet-5"
    assert get_tier("design").model == "claude-opus-4-8"
    ent = get_tier("enterprise")
    assert ent.model == "claude-opus-4-8"
    assert ent.max_output_tokens > get_tier("design").max_output_tokens
    assert not get_tier("free").paid
    assert all(TIERS[t].paid for t in ("hobby", "pro", "design", "enterprise"))


def test_tier_budgets_scale_upwards():
    order = ["free", "hobby", "pro", "design", "enterprise"]
    tokens = [TIERS[t].max_output_tokens for t in order]
    context = [TIERS[t].max_context_chars for t in order]
    assert tokens == sorted(tokens)
    assert context == sorted(context)


def test_unknown_tier_rejected():
    with pytest.raises(ValueError, match="unknown tier"):
        get_tier("platinum")


# ---------------------------------------------------------------------------
# Framework aliasing + context

def test_framework_aliases():
    assert corpus_framework_for("TILA") == "Reg_Z"
    assert corpus_framework_for("Reg_DD") == "Reg_DD"
    assert corpus_framework_for("CFPB") == "UDAAP"
    assert corpus_framework_for("FTC") == "FTC"
    assert corpus_framework_for("SomethingNew") == "SomethingNew"  # pass-through


def test_build_queries_prefers_claims_and_key_segments():
    queries = build_queries(_nlp_result())
    assert "Earn 4.50% APY on every dollar" in queries
    # disclosure segment included; duplicates collapsed
    assert any("APY accurate as of" in q for q in queries)
    assert len(queries) == len({q.lower() for q in queries})


def test_build_context_filters_per_framework_and_caps():
    nlp = _nlp_result()
    tier = get_tier("free")
    retriever = _fake_retriever(chunks_per_call=5)
    ctx = build_context(nlp, tier, retriever=retriever, conn=None, embedder=None)
    assert set(ctx.chunks_by_framework) == {"Reg_DD", "FTC"}
    for fw, chunks in ctx.chunks_by_framework.items():
        assert len(chunks) <= tier.max_chunks_per_framework
    # retrieval was filtered by the corpus label of each NLP framework
    used_filters = {tuple(c["frameworks"]) for c in retriever.calls}
    assert ("Reg_DD",) in used_filters and ("FTC",) in used_filters
    assert ctx.corpus_hash != "empty" and len(ctx.corpus_hash) == 16


def test_context_empty_framework_noted_in_prompt():
    nlp = _nlp_result()

    def empty_retriever(conn, embedder, query, *, k, frameworks, jurisdictions, as_of):
        return []

    ctx = build_context(nlp, get_tier("free"), retriever=empty_retriever,
                        conn=None, embedder=None)
    text = format_excerpts(ctx, 10_000)
    assert "no regulation text retrieved" in text
    assert ctx.corpus_hash == "empty"


def test_prompt_respects_context_char_budget():
    ctx = ReviewContext(frameworks=["Reg_DD"])
    ctx.chunks_by_framework["Reg_DD"] = [_chunk(f"c{i}") for i in range(50)]
    small = format_excerpts(ctx, 800)
    assert len(small) < 2_000
    assert "further excerpts omitted" in small


# ---------------------------------------------------------------------------
# Schema validation

def test_validate_llm_output_accepts_good_payload():
    validate_llm_output(_llm_payload())


def test_validate_llm_output_rejects_bad_payloads():
    with pytest.raises(SchemaError):
        validate_llm_output([])
    with pytest.raises(SchemaError, match="missing key"):
        validate_llm_output({"findings": []})
    bad = _llm_payload()
    bad["findings"][0]["severity"] = "catastrophic"
    del bad["findings"][0]["scope_of_improvement"]
    with pytest.raises(SchemaError) as err:
        validate_llm_output(bad)
    assert any("severity" in p for p in err.value.problems)
    assert any("scope_of_improvement" in p for p in err.value.problems)


# ---------------------------------------------------------------------------
# Engine

def test_review_asset_end_to_end_shape():
    nlp = _nlp_result()
    provider = FakeProvider(_llm_payload())
    result = review_asset(nlp, "pro", retriever=_fake_retriever(),
                          provider=provider, conn=None, embedder=None)

    # sample_output-LLMresponse.json shape
    assert list(result) == ["asset_id", "findings", "reviewed_clear",
                            "frameworks_evaluated", "llm_meta"]
    assert result["asset_id"] == nlp["asset_id"]
    assert result["findings"][0]["scope_of_improvement"]
    meta = result["llm_meta"]
    assert meta["tier"] == "pro"
    assert meta["model"] == "fake-model"
    assert meta["prompt_version"].startswith("compliance-review-")
    assert meta["rag_corpus_hash"] != "empty"
    assert meta["latency_ms"] >= 0
    assert meta["reviewed_at"].endswith("Z")

    # the provider saw both the regulation excerpts and the asset JSON
    _tier, system, user = provider.seen[0]
    assert "compliance reviewer" in system
    assert "12 CFR § 1030.8" in user
    assert nlp["asset_id"] in user


def test_review_asset_sanitizes_hallucinated_citations():
    payload = _llm_payload()
    payload["findings"][0]["cited_segment_ids"] = ["seg_1", "seg_999"]
    payload["findings"][0]["cited_entity_ids"] = ["ent_1", "ent_999"]
    payload["findings"][0]["claim_candidate_id"] = "clm_999"
    payload["reviewed_clear"] = ["seg_2", "ghost_7"]
    result = review_asset(_nlp_result(), "free", retriever=_fake_retriever(),
                          provider=FakeProvider(payload), conn=None, embedder=None)
    finding = result["findings"][0]
    assert finding["cited_segment_ids"] == ["seg_1"]
    assert finding["cited_entity_ids"] == ["ent_1"]
    assert finding["claim_candidate_id"] is None
    assert result["reviewed_clear"] == ["seg_2"]


def test_review_asset_rejects_unusable_input():
    with pytest.raises(ReviewError, match="asset_id"):
        review_asset({}, "free", provider=FakeProvider(_llm_payload()))
    no_frameworks = _nlp_result()
    no_frameworks["routing"]["frameworks"] = []
    with pytest.raises(ReviewError, match="frameworks"):
        review_asset(no_frameworks, "free", provider=FakeProvider(_llm_payload()))


def test_user_prompt_contains_full_nlp_json():
    nlp = _nlp_result()
    ctx = ReviewContext(frameworks=["Reg_DD"])
    ctx.chunks_by_framework["Reg_DD"] = [_chunk("c1")]
    prompt = build_user_prompt(nlp, ctx, 10_000)
    for seg in nlp["segments"]:
        assert seg["segment_id"] in prompt

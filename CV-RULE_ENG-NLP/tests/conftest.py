"""Shared fixtures for the three-layer test suite.

Layer selection: run each layer independently —
    pytest tests/test_nlp.py
    pytest tests/test_cv.py
    pytest tests/test_rule_engine_suite.py

Determinism: no network, no model downloads. The frozen embedding model
is monkeypatched out of fallback tests (real inference lives in the
`embed`-marked tests and uses the locally cached snapshot only); OCR
engines are faked. GPU note: this environment has no CUDA device and
CPU-only paddle/torch builds — all tests run on CPU by design.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


# ---------------------------------------------------------------- data
# Reference pairs are SYNTHETIC and committed in code: the real gold
# corpus (data/) lives outside git (.gitignore) and must never be a test
# dependency. Each pair preserves the intent of the old gold-backed
# regression gates: reviews pass; two assets carry deliberate,
# deterministic asset defects (FTC5-STR-001 / FTC5-STR-002).


def _reference_pairs() -> dict:
    """asset_id -> (AssetRepresentation dict, known-passing LLMOutput)."""
    pairs = {}

    # ref_clean — a well-formed credit ad with a clean review.
    s1 = make_segment(1, "Only $199 per month for 36 months", "headline",
                      bbox=(0.1, 0.1, 0.8, 0.06))
    s2 = make_segment(2, "17.5% APR. Terms and conditions apply.",
                      "fine_print", bbox=(0.1, 0.85, 0.5, 0.02))
    a = make_asset(
        [s1, s2], product="personal_loan",
        fws=["FTC", "TILA", "CFPB", "ECOA"],
        ents=[make_entity(1, "amount", "$199", s1, 199.0),
              make_entity(2, "time_period", "36 months", s1, 1095.75),
              make_entity(3, "apr", "17.5% APR", s2, 17.5)],
        clms=[{"claim_id": "clm_1", "claim_type": "pricing",
               "text": "Only $199 per month", "segment_id": "seg_1",
               "char_span": {"start": 0, "end": 19},
               "entity_ids": ["ent_1"], "pattern_id": "ref"}],
        cv=[{"finding_id": "cvf_p1", "measurement": "disclosure_proximity",
             "value": 0.30, "segment_id": "seg_1",
             "related_segment_id": "seg_2", "method": "ref"}],
        aid="ref_clean")
    o = make_output(
        findings=[make_finding("f1", "FTC", segs=["seg_1"], ents=["ent_1"],
                               quote="Only $199 per month", claim="clm_1"),
                  make_finding("f2", "TILA", segs=["seg_2"], ents=["ent_3"],
                               quote="17.5% APR")],
        ev=["FTC", "TILA", "CFPB", "ECOA"], aid="ref_clean")
    pairs["ref_clean"] = (a, o)

    # ref_str001 — deliberate FTC5-STR-001 true positive: absolute-claim
    # language with no disclosure/fine_print/legal segment anywhere.
    s1 = make_segment(1, "Guaranteed approval for every applicant",
                      "headline")
    a = make_asset([s1], product="unknown", fws=["FTC"],
                   ents=[make_entity(1, "guarantee_term", "Guaranteed", s1)],
                   aid="ref_str001")
    o = make_output(
        findings=[make_finding("f1", "FTC", segs=["seg_1"], ents=["ent_1"])],
        ev=["FTC"], aid="ref_str001")
    pairs["ref_str001"] = (a, o)

    # ref_str002 — deliberate FTC5-STR-002 true positive: the nearest
    # disclosure is measurably too far from the claim (0.90 > PROX_MAX).
    s1 = make_segment(1, "Save 72% on interest today", "headline",
                      bbox=(0.1, 0.05, 0.8, 0.06))
    s2 = make_segment(2, "Savings vary by borrower. Terms apply.",
                      "disclosure", bbox=(0.1, 0.95, 0.5, 0.02))
    a = make_asset(
        [s1, s2], product="unknown", fws=["FTC"],
        ents=[make_entity(1, "percentage", "72%", s1, 72.0)],
        clms=[{"claim_id": "clm_1", "claim_type": "pricing",
               "text": "Save 72% on interest today", "segment_id": "seg_1",
               "char_span": {"start": 0, "end": 26},
               "entity_ids": ["ent_1"], "pattern_id": "ref"}],
        cv=[{"finding_id": "cvf_p1", "measurement": "disclosure_proximity",
             "value": 0.90, "segment_id": "seg_1",
             "related_segment_id": "seg_2", "method": "ref"}],
        aid="ref_str002")
    o = make_output(
        findings=[make_finding("f1", "FTC", segs=["seg_1"], ents=["ent_1"],
                               quote="Save 72% on interest today",
                               claim="clm_1")],
        clear=["seg_2"], ev=["FTC"], aid="ref_str002")
    pairs["ref_str002"] = (a, o)
    return pairs


@pytest.fixture(scope="session")
def gold_assets() -> dict:
    """asset_id -> reference AssetRepresentation dict (synthetic)."""
    return {aid: a for aid, (a, _o) in _reference_pairs().items()}


@pytest.fixture(scope="session")
def reference_outputs() -> dict:
    """asset_id -> known-passing LLMOutput dict (synthetic)."""
    return {aid: o for aid, (_a, o) in _reference_pairs().items()}


# ------------------------------------------------------------ builders

def make_segment(i, text, role="body", bbox=None, source="text"):
    d = {"segment_id": f"seg_{i}", "text": text, "role": role,
         "source": source}
    if bbox:
        d["bbox"] = {"x": bbox[0], "y": bbox[1],
                     "width": bbox[2], "height": bbox[3]}
    return d


def make_entity(i, etype, raw, segd, value=None):
    start = segd["text"].index(raw)
    return {"entity_id": f"ent_{i}", "entity_type": etype, "raw_text": raw,
            "normalized_value": value, "segment_id": segd["segment_id"],
            "char_span": {"start": start, "end": start + len(raw)}}


def make_asset(segs, product="unknown", fws=("FTC",), ents=(), clms=(),
               cv=(), juris=(), aid="test_asset"):
    return {"asset_id": aid, "segments": list(segs), "entities": list(ents),
            "claim_candidates": list(clms), "cv_findings": list(cv),
            "routing": {"product_type": product, "frameworks": list(fws),
                        "signal": "test"},
            "target_jurisdictions": list(juris),
            "provenance": {"cv_version": "t", "nlp_version": "t",
                           "ruleset_hash": "t",
                           "timestamp": "2026-07-10T00:00:00Z"}}


def make_output(findings=(), clear=(), ev=("FTC",), aid="test_asset",
                meta=None):
    return {"asset_id": aid, "findings": list(findings),
            "reviewed_clear": list(clear),
            "frameworks_evaluated": list(ev),
            "llm_meta": meta if meta is not None
            else {"model": "t", "prompt_version": "t"}}


def make_finding(fid, fw="FTC", verdict="compliant", sev="low", segs=(),
                 ents=(), quote=None, claim=None, reasoning="test"):
    return {"finding_id": fid, "framework": fw, "severity": sev,
            "verdict": verdict, "cited_segment_ids": list(segs),
            "cited_entity_ids": list(ents), "quoted_evidence": quote,
            "claim_candidate_id": claim, "reasoning": reasoning}


@pytest.fixture()
def builders():
    """Bundle the dict builders for convenient injection."""
    return {"segment": make_segment, "entity": make_entity,
            "asset": make_asset, "output": make_output,
            "finding": make_finding}


# ----------------------------------------------- engine registry guard

@pytest.fixture()
def clean_registry():
    """Snapshot/restore CHECK_REGISTRY so tests that register throwaway
    checks cannot leak into other tests."""
    from rule_engine.core import CHECK_REGISTRY

    snapshot = dict(CHECK_REGISTRY)
    yield CHECK_REGISTRY
    CHECK_REGISTRY.clear()
    CHECK_REGISTRY.update(snapshot)


# --------------------------------------------------------- OCR fakes

class FakePaddlePipeline:
    """Deterministic stand-in for a PaddleOCR pipeline: returns two
    fixed lines regardless of image content (pixel-space coords are
    normalized against the image the caller passes in)."""

    def predict(self, img):
        h, w = img.shape[:2]
        return [{
            "rec_texts": ["Earn 4.50% APY today", "#ad Sponsored"],
            "rec_scores": [0.98, 0.91],
            "rec_polys": [
                [(int(w * .1), int(h * .1)), (int(w * .9), int(h * .1)),
                 (int(w * .9), int(h * .2)), (int(w * .1), int(h * .2))],
                [(int(w * .1), int(h * .8)), (int(w * .5), int(h * .8)),
                 (int(w * .5), int(h * .85)), (int(w * .1), int(h * .85))],
            ],
        }]


@pytest.fixture()
def fake_paddle_engine(monkeypatch):
    """Force cv.ocr onto the fake paddle backend (no model download,
    no real inference); restores the real lazy engine afterwards."""
    import cv.ocr as ocr

    monkeypatch.setattr(ocr, "_engine", ("paddle", FakePaddlePipeline()))
    return ocr


@pytest.fixture()
def tiny_images(tmp_path):
    """Small real image files in several formats, written with cv2."""
    import numpy as np
    import cv2

    img = np.full((60, 120, 3), 255, dtype=np.uint8)
    img[10:20, 10:110] = 0  # a black bar so files aren't degenerate
    paths = {}
    for ext in ("png", "jpg", "bmp"):
        p = tmp_path / f"tiny.{ext}"
        assert cv2.imwrite(str(p), img)
        paths[ext] = str(p)
    return paths


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "embed: loads the real frozen embedding model "
        "(cached locally; slower)")
    config.addinivalue_line(
        "markers", "ocr_engine: runs a real OCR backend (very slow; "
        "opt in with RUN_OCR_TESTS=1)")


deep = copy.deepcopy  # convenience alias for tests

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
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


# ---------------------------------------------------------------- data

@pytest.fixture(scope="session")
def gold_assets() -> dict:
    """asset_id -> gold AssetRepresentation dict."""
    out = {}
    for p in sorted((REPO / "data" / "gold").glob("*.json")):
        d = json.loads(p.read_text())
        out[d["asset_id"]] = d
    return out


@pytest.fixture(scope="session")
def reference_outputs() -> dict:
    """asset_id -> known-passing LLMOutput dict."""
    out = {}
    for p in sorted((REPO / "data" / "llm_outputs" / "gold").glob("*.json")):
        d = json.loads(p.read_text())
        out[d["asset_id"]] = d
    return out


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

"""Invariants for the synthetic-data generator and eval harness.

These guard the evaluation infrastructure itself: if the generator stops
producing schema-valid, span-exact, reproducible assets, every measured
"improvement" downstream becomes untrustworthy.
"""

from __future__ import annotations

import json

import pytest

import schema
from synth.generator import generate_asset, generate_corpus, augment_ocr_noise
import random


def test_corpus_is_schema_valid_and_span_exact():
    corpus = generate_corpus(60, seed=3)
    for a in corpus:
        schema.AssetRepresentation.model_validate(a)
        by_id = {s["segment_id"]: s["text"] for s in a["segments"]}
        for e in a["entities"]:
            cs = e["char_span"]
            assert by_id[e["segment_id"]][cs["start"]:cs["end"]] == e["raw_text"]
            # numeric normalization is never None for numeric types
            if e["entity_type"] in ("apr", "amount", "percentage", "time_period"):
                assert e["normalized_value"] is not None


def test_generation_is_reproducible():
    assert json.dumps(generate_corpus(40, seed=11)) == \
        json.dumps(generate_corpus(40, seed=11))
    assert json.dumps(generate_corpus(40, seed=11)) != \
        json.dumps(generate_corpus(40, seed=12))


def test_claim_ground_truth_never_on_boilerplate():
    for a in generate_corpus(80, seed=5):
        boilerplate = {s["segment_id"] for s in a["segments"]
                       if s["role"] in ("disclosure", "legal", "fine_print")}
        for c in a["claim_candidates"]:
            assert c["segment_id"] not in boilerplate


def test_routing_frameworks_are_valid_enum_values():
    valid = {f.value for f in schema.Framework}
    for a in generate_corpus(50, seed=9):
        assert a["routing"]["frameworks"], "at least FTC must be present"
        for f in a["routing"]["frameworks"]:
            assert f in valid


def test_mini_tcpa_state_mirror_matches_router():
    # The generator keeps a literal mirror of the router's mini-TCPA
    # state list for ground-truth routing; they must never drift.
    from nlp.routing_lexicon import MINI_TCPA_STATES
    from synth.generator import _MINI_TCPA_STATES
    assert _MINI_TCPA_STATES == MINI_TCPA_STATES


def test_ocr_noise_augmentation_preserves_labels():
    corpus = generate_corpus(20, seed=1)
    a = next(x for x in corpus if x["entities"])
    noisy = augment_ocr_noise(a, random.Random(2))
    # roles, claim types, and routing survive corruption.
    assert [s["role"] for s in noisy["segments"]] == [s["role"] for s in a["segments"]]
    assert noisy["routing"] == a["routing"]
    # Entity labels are PRESERVED under noise (clean and noisy share labels):
    # spans stay exact against the corrupted text and numeric normalized
    # values are unchanged, because digit cores are protected from corruption.
    assert noisy["entities"], "entities must survive noise augmentation"
    by_id = {s["segment_id"]: s["text"] for s in noisy["segments"]}
    clean_vals = {e["entity_id"]: e["normalized_value"] for e in a["entities"]}
    for e in noisy["entities"]:
        cs = e["char_span"]
        assert by_id[e["segment_id"]][cs["start"]:cs["end"]] == e["raw_text"]
        assert e["normalized_value"] == clean_vals[e["entity_id"]]


def test_negative_assets_have_no_entities():
    # The distribution includes financial-sounding negatives (no extractable
    # entities) to measure false positives; they must be schema-valid and
    # entity-free.
    negs = [a for a in generate_corpus(200, seed=7) if a.get("negative")]
    assert negs, "expected some negative assets in the distribution"
    for a in negs:
        schema.AssetRepresentation.model_validate(a)
        assert a["entities"] == []


def test_harness_runs_text_mode_and_scores():
    from synth.evaluate import score_text_corpus
    r = score_text_corpus(generate_corpus(12, seed=7))
    # The distribution deliberately includes phrasing families the current
    # patterns were not written against, so overall F1 is intentionally below
    # the V1 bar. This floor only guards against catastrophic breakage of the
    # harness/extractor, not the (expected) phrasing-coverage gaps.
    assert r["entities"]["overall"]["f1"] > 0.7
    assert r["claims"]["recall"] > 0.75

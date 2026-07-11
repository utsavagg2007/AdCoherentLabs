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


def test_ocr_noise_augmentation_preserves_labels():
    a = generate_asset(random.Random(1), 0)
    noisy = augment_ocr_noise(a, random.Random(2))
    # roles, claim types, and routing survive corruption; spans are dropped.
    assert [s["role"] for s in noisy["segments"]] == [s["role"] for s in a["segments"]]
    assert noisy["routing"] == a["routing"]
    assert noisy["entities"] == []


def test_harness_runs_text_mode_and_scores():
    from synth.evaluate import score_text_corpus
    r = score_text_corpus(generate_corpus(12, seed=7))
    # On clean, consistently-labeled synthetic text the deterministic
    # extractor should be strong — a floor guards against silent breakage.
    assert r["entities"]["overall"]["f1"] > 0.9
    assert r["claims"]["recall"] > 0.8

"""Shared __main__ demo for nlp/claims.py and nlp/routing.py:
run both against one real gold asset and print output next to gold."""

from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ASSET = "881224884306098"  # Reach Financial personal-loan ad


def run(asset_id: str = _ASSET) -> None:
    sys.path.insert(0, _ROOT)
    import schema
    from nlp.claims import detect_claims
    from nlp.entities import extract_entities
    from nlp.routing import route

    with open(os.path.join(_ROOT, f"data/gold/{asset_id}.json")) as f:
        gold = json.load(f)

    segments = gold["segments"]
    entities = extract_entities(segments)

    claims = detect_claims(segments, entities)
    routing = route(segments, entities)
    for c in claims:
        schema.ClaimCandidate.model_validate(c)  # prove schema shape
    schema.RoutingLabel.model_validate(routing)

    print(f"asset: {asset_id}\n")
    print(f"PREDICTED claims ({len(claims)}):")
    for c in claims:
        print(f"  {c['claim_type']:<12} [{c['segment_id']}] "
              f"pattern={c['pattern_id']:<15} entities={len(c['entity_ids'])} "
              f"{c['text'][:60]!r}")
    print(f"\nGOLD claims ({len(gold['claim_candidates'])}):")
    for c in gold["claim_candidates"]:
        print(f"  {c['claim_type']:<12} [{c['segment_id']}] "
              f"{c['text'][:60]!r}")

    print(f"\nPREDICTED routing: {routing['product_type']} "
          f"{routing['frameworks']}\n  signal: {routing['signal']}")
    g = gold["routing"]
    print(f"\nGOLD routing:      {g['product_type']} {g['frameworks']}\n"
          f"  signal: {g['signal']}")

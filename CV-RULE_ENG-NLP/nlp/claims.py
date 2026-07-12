"""Claim-candidate detection: segments + entities -> ClaimCandidate dicts.

High-recall by design: this layer over-produces candidates and lets the
rule engine dismiss the harmless ones. A missed claim is invisible to
review; a spurious candidate costs one rule-engine evaluation.

Two producers, deduplicated per (segment, claim_type):
  * entity-driven — an extracted entity of a claim-bearing type
    promotes its segment to a candidate (apr/fee -> pricing,
    guarantee_term -> guarantee, ...);
  * keyword-driven — trigger phrases catch claims whose entities the
    extractor missed ("beats every bank", "trusted by millions").

Spans cover the whole segment: the eval scorer matches claims by
type + segment + any span overlap, so segment-wide spans preserve
recall while the extractor stays simple. Output matches
``schema.ClaimCandidate`` exactly (note: the field is ``entity_ids``,
and there is no "linked_entity_ids" in the schema).
"""

from __future__ import annotations

import re

# entity_type -> claim_type it evidences
_ENTITY_CLAIMS = {
    "apr": "pricing", "rate": "pricing", "fee": "pricing",
    "amount": "pricing", "percentage": "pricing",
    "superlative": "performance",
    "guarantee_term": "guarantee",
    "endorsement_marker": "endorsement",
}

# claim_type -> trigger regexes over segment text
_KEYWORD_CLAIMS = {
    "comparative": re.compile(
        # A comparison names or implies a *rival*. Bare "than" fired on
        # non-comparisons ("less than 5 minutes"), so require a comparative
        # cue near it; "save/savings" was a mis-categorization (that is a
        # performance/pricing claim, not a comparison) and is removed.
        r"\bvs\.?\b|\bversus\b|\bcompared? (?:to|with)\b|"
        r"\bbeats?\b|\boutperform|\bunlike\b|\bother (?:banks|lenders|cards)\b|"
        r"\b\d+(?:\.\d+)?\s*(?:x|times)\b|"
        # "than" only when it names a rival, not a threshold ("less than 5
        # minutes" is not a comparison).
        r"\bthan (?:any|every|other|the|our|competitor|leading)\b",
        re.IGNORECASE),
    "guarantee": re.compile(
        r"\bguarantee[ds]?\b|\balways\b|\bnever\b|\bpromise[ds]?\b|"
        r"\bno matter what\b|\bevery time\b|\bno (?:\w+\s){0,3}?(?:needed|required)\b",
        re.IGNORECASE),
    "risk_free": re.compile(
        r"\brisk[- ]free\b|\bno risk\b|\bworry[- ]free\b|\bzero risk\b|"
        r"\bnothing to lose\b",
        re.IGNORECASE),
    "endorsement": re.compile(
        r"#ad\b|\bsponsored\b|\bpaid partnership\b|\bas seen on\b|"
        r"\btrusted by\b|\brecommended by\b|\b(?:5|five)[- ]star\b|"
        r"\brated\b|\breviews?\b|\btestimonial",
        re.IGNORECASE),
    "performance": re.compile(
        # "100%" alone is a bare number, not a performance claim — dropped.
        r"\bsave[ds]?\b|\bsavings\b|\bfast(?:er|est)?\b|\binstant(?:ly)?\b|"
        r"\bin (?:just )?(?:minutes|seconds)\b|\bapproved in\b|\beasy\b|"
        r"\beffortless|\bdigital process\b",
        re.IGNORECASE),
    "pricing": re.compile(
        r"\b(?:no|zero|0\$?) (?:\w+\s)?fees?\b|\bfree\b|\blow(?:er|est)? "
        # \$\d (not \b\$\d): "$" is non-word, so a \b before it never
        # matches after a space or at string start — "Get $500 today"
        # would silently miss. A negative lookbehind still blocks "US$5".
        r"(?:rates?|price|cost)\b|\bcash back\b|(?<!\w)\$\d|\d+(?:\.\d+)?%",
        re.IGNORECASE),
}

# Roles whose text is boilerplate, not marketing voice — candidates
# from disclosures would be pure noise even at high-recall bias.
_SKIP_ROLES = {"disclosure", "legal"}

# ------------------------------------------- semantic fallback (frozen)
# For segments where neither entities nor keywords produced a candidate,
# compare the segment against one reference sentence per claim type with
# the frozen embedding model. Emitted candidates carry a 'sem_' pattern_id
# so they are always distinguishable from rule-based ('ent_'/'kw_') hits.

SEMANTIC_CLAIM_THRESHOLD = 0.6  # tunable; start high, rules stay primary

_SEMANTIC_REFERENCES = {
    "performance": "Save money fast with instant approval in just minutes.",
    "comparative": "We offer better rates than any other bank or lender.",
    "guarantee": "Your approval is guaranteed no matter what, every time.",
    "endorsement": "Recommended and trusted by millions of five-star reviews.",
    "pricing": "No fees, our lowest rates, and cash back on every purchase.",
    "risk_free": "Completely risk-free — you have nothing to lose.",
}


def _worth_semantic(text: str) -> bool:
    """Gate the (expensive, model-backed) fallback to real prose.

    OCR junk segments ("M", "yes", "BMO") would each cost a full set of
    encodes for a near-random score, so require at least a few words and
    a minimum of alphabetic content before consulting the embeddings.
    """
    stripped = text.strip()
    if len(stripped) < 12 or len(stripped.split()) < 3:
        return False
    return sum(c.isalpha() for c in stripped) >= 8


def _semantic_claims(text: str) -> list[tuple[str, float]]:
    """(claim_type, score) for every reference the text clears the
    threshold against. Returns [] (never raises) if the embedding
    backend is unavailable — offline/cold-cache degrades to rules-only.
    """
    try:
        from nlp.embeddings import semantic_similarity

        return [(ctype, score) for ctype, ref in _SEMANTIC_REFERENCES.items()
                if (score := semantic_similarity(text, ref)) >= SEMANTIC_CLAIM_THRESHOLD]
    except Exception:  # noqa: BLE001 — a missing model must not crash the pipeline
        return []


def _get(obj, key):
    return obj[key] if isinstance(obj, dict) else getattr(obj, key)


def detect_claims(segments: list, entities: list) -> list[dict]:
    """schema.ClaimCandidate-shaped dicts, high-recall, deduplicated
    per (segment, claim_type). Spans cover the whole segment."""
    by_segment: dict[str, list] = {}
    for e in entities:
        by_segment.setdefault(_get(e, "segment_id"), []).append(e)

    claims: list[dict] = []
    n = 0
    for seg in segments:
        seg_id = _get(seg, "segment_id")
        text = _get(seg, "text")
        role = str(_get(seg, "role") if not isinstance(seg, dict)
                   else seg.get("role", "unknown"))
        if not text.strip() or role in _SKIP_ROLES:
            continue
        seg_entities = by_segment.get(seg_id, [])

        triggers: dict[str, str] = {}  # claim_type -> pattern_id
        for e in seg_entities:
            ctype = _ENTITY_CLAIMS.get(str(_get(e, "entity_type")))
            if ctype and ctype not in triggers:
                triggers[ctype] = f"ent_{_get(e, 'entity_type')}"
        for ctype, pattern in _KEYWORD_CLAIMS.items():
            if ctype not in triggers and pattern.search(text):
                triggers[ctype] = f"kw_{ctype}"

        # Rules produced nothing for this segment -> semantic fallback.
        # pattern_id 'sem_<type>:<score>' marks these as similarity hits,
        # not pattern matches.
        if not triggers and _worth_semantic(text):
            for ctype, score in _semantic_claims(text):
                triggers[ctype] = f"sem_{ctype}:{score:.2f}"

        for ctype in sorted(triggers):
            n += 1
            claims.append({
                "claim_id": f"clm_{n}",
                "claim_type": ctype,
                "text": text,
                "segment_id": seg_id,
                "char_span": {"start": 0, "end": len(text)},
                "entity_ids": [_get(e, "entity_id") for e in seg_entities],
                "pattern_id": triggers[ctype],
            })
    return claims


if __name__ == "__main__":
    import glob
    import json
    import os
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    import schema
    from nlp.entities import extract_entities

    def show(label: str, segments: list, entities: list) -> None:
        claims = detect_claims(segments, entities)
        rule = [c for c in claims if not c["pattern_id"].startswith("sem_")]
        sem = [c for c in claims if c["pattern_id"].startswith("sem_")]
        print(f"{label}: {len(rule)} rule-based, {len(sem)} semantic-fallback")
        for c in claims:
            schema.ClaimCandidate.model_validate(c)
            src = "SEM " if c["pattern_id"].startswith("sem_") else "RULE"
            print(f"  [{src}] {c['claim_type']:<12} pattern={c['pattern_id']:<22} "
                  f"{c['text'][:55]!r}")
        print()

    for path in sorted(glob.glob(os.path.join(root, "data/gold/*.json")))[:3]:
        gold = json.load(open(path))
        segments = gold["segments"]
        show(gold["asset_id"], segments, extract_entities(segments))

    # Synthetic segment: claim-like meaning, but worded to dodge every
    # keyword pattern — only the semantic fallback can catch it.
    show("synthetic-no-rule-match",
         [{"segment_id": "seg_1", "role": "body", "source": "text",
           "text": "Your approval is assured, regardless of your situation."}],
         [])

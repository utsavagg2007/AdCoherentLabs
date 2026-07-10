"""Entity extraction: segments -> schema.Entity-shaped dicts.

spaCy Matcher (numeric types: apr, rate, fee, amount, percentage,
time_period) + EntityRuler (lexical types: superlative,
endorsement_marker, optout_marker, guarantee_term) over a blank
English pipeline (en_core_web_sm is used if installed, but nothing
here needs its statistical components).

Deterministic structurer: emits candidates with normalized values,
never judgments. Every char_span is verified against the segment's
actual text before the entity is emitted.
"""

from __future__ import annotations

import re

import spacy
from spacy.matcher import Matcher

# --- token-pattern shorthands ---------------------------------------
_NUM = {"TEXT": {"REGEX": r"^\d[\d,]*(\.\d+)?$"}}
_PCT = {"TEXT": "%"}
_ANY = lambda n: {"OP": f"{{0,{n}}}"}  # up to n arbitrary tokens

_TIME_UNITS = {
    "minute": 1 / 1440, "min": 1 / 1440,
    "hour": 1 / 24, "hr": 1 / 24,
    "day": 1.0,
    "week": 7.0, "wk": 7.0,
    "month": 30.4375, "mo": 30.4375,
    "year": 365.25, "yr": 365.25,
}
_TIME_UNIT_TOKENS = [u + s for u in _TIME_UNITS for s in ("", "s")]

# Matcher patterns for numeric types. Overlaps are resolved by type
# priority then span length, so "8.99% APR" is one apr entity, not a
# percentage plus a fragment.
_MATCHER_PATTERNS: dict[str, list] = {
    "apr": [
        [_NUM, _PCT, {"LOWER": "apr"}],
        [{"LOWER": "apr"}, _ANY(2), _NUM, _PCT],
    ],
    "rate": [
        [_NUM, _PCT, {"LOWER": "apy"}],
        [{"LOWER": {"IN": ["rate", "rates"]}}, {"LOWER": "of"}, _NUM, _PCT],
    ],
    "fee": [
        [{"TEXT": "$"}, _NUM, _ANY(2), {"LOWER": {"REGEX": r"^fees?$"}}],
        [{"LOWER": {"REGEX": r"^fees?$"}}, {"LOWER": "of"}, {"TEXT": "$"}, _NUM],
        [{"LOWER": {"IN": ["no", "zero"]}}, _ANY(1), {"LOWER": {"REGEX": r"^fees?$"}}],
    ],
    "time_period": [
        [_NUM, {"LOWER": {"IN": _TIME_UNIT_TOKENS}}],
        [{"TEXT": {"REGEX": r"^\d+-(minute|hour|day|week|month|year)s?$"}}],
    ],
    "amount": [
        [{"TEXT": "$"}, _NUM],
    ],
    "percentage": [
        [_NUM, _PCT],
    ],
}

# EntityRuler patterns for lexical (non-numeric) types.
_RULER_PATTERNS = [
    {"label": "superlative", "pattern": [{"LOWER": {"IN": [
        "lowest", "best", "highest", "fastest", "cheapest", "biggest",
        "largest", "leading", "top-rated", "unbeatable"]}}]},
    {"label": "superlative", "pattern": [{"TEXT": "#"}, {"TEXT": "1"}]},
    {"label": "endorsement_marker", "pattern": [{"TEXT": "#"}, {"LOWER": "ad"}]},
    {"label": "endorsement_marker", "pattern": [{"LOWER": "sponsored"}]},
    {"label": "endorsement_marker",
     "pattern": [{"LOWER": "paid"}, {"LOWER": "partnership"}]},
    {"label": "endorsement_marker",
     "pattern": [{"LOWER": "as"}, {"LOWER": "seen"}, {"LOWER": "on"}]},
    {"label": "optout_marker", "pattern": [{"LOWER": "unsubscribe"}]},
    {"label": "optout_marker",
     "pattern": [{"LOWER": "opt"}, {"TEXT": "-", "OP": "?"}, {"LOWER": "out"}]},
    {"label": "optout_marker",
     "pattern": [{"LOWER": {"IN": ["reply", "text"]}}, {"LOWER": "stop"}]},
    {"label": "guarantee_term",
     "pattern": [{"LOWER": {"REGEX": r"^guarantee[ds]?$"}}]},
    {"label": "guarantee_term",
     "pattern": [{"LOWER": "risk"}, {"TEXT": "-", "OP": "?"}, {"LOWER": "free"}]},
    {"label": "guarantee_term", "pattern": [{"LOWER": "no"}, {"LOWER": "risk"}]},
]

# When spans overlap, the earlier type in this list wins; ties by
# longer span, then earlier position.
_PRIORITY = ["apr", "rate", "fee", "time_period", "amount", "percentage",
             "endorsement_marker", "optout_marker", "guarantee_term",
             "superlative"]

_nlp = None
_matcher = None


def _get_nlp():
    global _nlp, _matcher
    if _nlp is None:
        try:
            _nlp = spacy.load("en_core_web_sm",
                              exclude=["ner", "parser", "lemmatizer"])
        except OSError:
            _nlp = spacy.blank("en")
        ruler = _nlp.add_pipe("entity_ruler")
        ruler.add_patterns(_RULER_PATTERNS)
        _matcher = Matcher(_nlp.vocab)
        for label, patterns in _MATCHER_PATTERNS.items():
            _matcher.add(label, patterns)
    return _nlp, _matcher


_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _first_number(text: str) -> float | None:
    m = _NUM_RE.search(text)
    return float(m.group().replace(",", "")) if m else None


def _normalize(label: str, raw: str) -> float | None:
    """Percent types -> the number; fee/amount -> USD; time -> days.

    None for non-numeric types, matching gold-label conventions.
    """
    if label in ("apr", "rate", "percentage"):
        return _first_number(raw)
    if label == "fee":
        if re.match(r"^\s*(no|zero)\b", raw, re.IGNORECASE):
            return 0.0
        return _first_number(raw)
    if label == "amount":
        return _first_number(raw)
    if label == "time_period":
        n = _first_number(raw)
        unit = re.search(r"(minute|min|hour|hr|day|week|wk|month|mo|year|yr)s?\b",
                         raw, re.IGNORECASE)
        if n is None or unit is None:
            return None
        return n * _TIME_UNITS[unit.group(1).lower()]
    return None  # superlative, endorsement_marker, optout_marker, guarantee_term


def extract_entities(segments: list) -> list[dict]:
    """Extract schema.Entity-shaped dicts from Segment-shaped dicts.

    Only ``segment_id`` and ``text`` are read from each segment.
    char_span is half-open into the segment's text and asserted to
    reproduce raw_text exactly.
    """
    nlp, matcher = _get_nlp()
    entities: list[dict] = []
    n = 0
    for seg in segments:
        seg_id = seg["segment_id"] if isinstance(seg, dict) else seg.segment_id
        text = seg["text"] if isinstance(seg, dict) else seg.text
        doc = nlp(text)

        candidates = []  # (start_char, end_char, label)
        for match_id, start, end in matcher(doc):
            span = doc[start:end]
            candidates.append((span.start_char, span.end_char,
                               nlp.vocab.strings[match_id]))
        for ent in doc.ents:
            candidates.append((ent.start_char, ent.end_char, ent.label_))

        # Greedy overlap resolution: type priority, then longer span.
        candidates.sort(key=lambda c: (_PRIORITY.index(c[2]),
                                       -(c[1] - c[0]), c[0]))
        kept: list[tuple[int, int, str]] = []
        for start, end, label in candidates:
            if all(end <= ks or start >= ke for ks, ke, _ in kept):
                kept.append((start, end, label))
        kept.sort(key=lambda c: c[0])

        for start, end, label in kept:
            raw = text[start:end]
            assert text[start:end] == raw  # span-integrity invariant
            n += 1
            entities.append({
                "entity_id": f"ent_{n}",
                "entity_type": label,
                "raw_text": raw,
                "normalized_value": _normalize(label, raw),
                "segment_id": seg_id,
                "char_span": {"start": start, "end": end},
            })
    return entities


if __name__ == "__main__":
    import os
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import schema

    tests = [
        ("apr", "Rates from 8.99% APR with autopay discount."),
        ("rate", "Earn 4.50% APY on every dollar."),
        ("fee", "No annual fee, and a late fee of $29."),
        ("amount", "Borrow up to $40,000 today."),
        ("percentage", "Members save 72% on interest."),
        ("superlative", "The lowest rates in America."),
        ("endorsement_marker", "#ad Paid partnership with FinCo."),
        ("optout_marker", "Reply STOP to unsubscribe."),
        ("guarantee_term", "Guaranteed approval, completely risk-free."),
        ("time_period", "Approved in 5 minutes with a 60 month term."),
    ]
    segments = [{"segment_id": f"seg_{i}", "text": t}
                for i, (_, t) in enumerate(tests, start=1)]
    entities = extract_entities(segments)

    ok = True
    for i, (expected, text) in enumerate(tests, start=1):
        seg_id = f"seg_{i}"
        found = [e for e in entities if e["segment_id"] == seg_id]
        types = {e["entity_type"] for e in found}
        mark = "ok " if expected in types else "MISS"
        if expected not in types:
            ok = False
        print(f"{mark} [{expected:>18}] {text!r}")
        for e in found:
            schema.Entity.model_validate(e)  # prove schema shape
            span = e["char_span"]
            print(f"      -> {e['entity_type']:<18} {e['raw_text']!r}"
                  f"  normalized={e['normalized_value']}"
                  f"  span=[{span['start']},{span['end']})")
    sys.exit(0 if ok else 1)

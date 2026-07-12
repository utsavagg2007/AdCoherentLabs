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
# _NUM also accepts Indian digit grouping ("5,00,000"); commas are
# stripped at normalization time.
_NUM = {"TEXT": {"REGEX": r"^\d[\d,]*(\.\d+)?$"}}
_PCT = {"TEXT": "%"}
_ANY = lambda n: {"OP": f"{{0,{n}}}"}  # up to n arbitrary tokens

# Currency prefix symbol ($, €, £, ₹, ¥) or a trailing/standalone ISO-ish
# code. Amounts are not $-only: real ad corpora carry ₹ / € / £, often
# with a magnitude word ("₹1.5 LAKH", "$75K").
_CUR_SYM = {"TEXT": {"REGEX": r"^[$€£₹¥]$"}}
_CUR_CODE = {"LOWER": {"IN": ["usd", "eur", "gbp", "inr", "cad", "aud", "rs"]}}
_MAG_TOKEN = {"LOWER": {"IN": ["k", "m", "mn", "b", "bn",
                               "lakh", "lac", "lakhs", "cr", "crore", "crores"]}}
# Magnitude multipliers for suffix words / letters in an amount's raw text.
_MAGNITUDES = {"k": 1e3, "m": 1e6, "mn": 1e6, "b": 1e9, "bn": 1e9,
               "lakh": 1e5, "lac": 1e5, "cr": 1e7, "crore": 1e7}
_MAG_RE = re.compile(r"(?<![A-Za-z])(k|m|mn|b|bn|lakhs?|lac|crores?|cr)(?![A-Za-z])",
                     re.IGNORECASE)

_TIME_UNITS = {
    "minute": 1 / 1440, "min": 1 / 1440,
    "hour": 1 / 24, "hr": 1 / 24,
    "day": 1.0,
    "week": 7.0, "wk": 7.0,
    "month": 30.4375, "mo": 30.4375,
    "year": 365.25, "yr": 365.25,
}
_TIME_UNIT_TOKENS = [u + s for u in _TIME_UNITS for s in ("", "s")]

# Spelled-out numbers ("twelve months", "twenty-four months"). Tens and
# ones compose hyphenated compounds; spaCy tokenizes "twenty-four" as
# ["twenty", "-", "four"].
_ONES_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
               "six": 6, "seven": 7, "eight": 8, "nine": 9}
_TEEN_WORDS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
               "fourteen": 14, "fifteen": 15, "sixteen": 16,
               "seventeen": 17, "eighteen": 18, "nineteen": 19}
_TENS_WORDS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
               "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_WORD_NUMS = {**_ONES_WORDS, **_TEEN_WORDS, **_TENS_WORDS}
_WORD_NUM_RE = re.compile(
    r"\b(" + "|".join(_TENS_WORDS) + r")(?:-(" + "|".join(_ONES_WORDS) + r"))?\b"
    r"|\b(" + "|".join(list(_ONES_WORDS) + list(_TEEN_WORDS)) + r")\b",
    re.IGNORECASE,
)


def _word_number(text: str) -> float | None:
    """First spelled-out number in ``text`` ("twenty-four" -> 24.0)."""
    m = _WORD_NUM_RE.search(text)
    if not m:
        return None
    tens, ones, simple = m.groups()
    if simple:
        return float(_WORD_NUMS[simple.lower()])
    return float(_TENS_WORDS[tens.lower()] + (_ONES_WORDS[ones.lower()] if ones else 0))


# Qualifiers that legitimately sit between "N %" and "APR" in promo copy
# ("0% intro APR for 15 months").
_APR_QUALIFIER = {"LOWER": {"IN": ["intro", "introductory", "promo",
                                   "promotional", "variable", "fixed"]}}
_DOLLARS_WORD = {"LOWER": {"IN": ["dollar", "dollars"]}}
_PERCENT_WORD = {"LOWER": "percent"}

# Matcher patterns for numeric types. Overlaps are resolved by type
# priority then span length, so "8.99% APR" is one apr entity, not a
# percentage plus a fragment.
_MATCHER_PATTERNS: dict[str, list] = {
    "apr": [
        [_NUM, _PCT, {"LOWER": "apr"}],
        [{"LOWER": "apr"}, _ANY(2), _NUM, _PCT],
        # Spelled-out "Annual Percentage Rate" (either order). Longer than
        # the bare "N %" percentage span, so overlap resolution (apr has
        # higher priority + longer span) keeps it as one apr entity.
        [_NUM, _PCT, {"LOWER": "annual"}, {"LOWER": "percentage"}, {"LOWER": "rate"}],
        [{"LOWER": "annual"}, {"LOWER": "percentage"}, {"LOWER": "rate"},
         _ANY(2), _NUM, _PCT],
        # "percent" written out: "9.49 percent APR" / "APR of 9.49 percent".
        [_NUM, _PERCENT_WORD, {"LOWER": "apr"}],
        [{"LOWER": "apr"}, _ANY(2), _NUM, _PERCENT_WORD],
        # Promo qualifier between "%" and "APR": "0% intro APR".
        [_NUM, _PCT, _APR_QUALIFIER, {"LOWER": "apr"}],
    ],
    "rate": [
        # Explicit "rate of X%" only. APY-stated yields are a percentage
        # per the gold labeling guide (gold labels "4.50% APY" as
        # percentage, span-including "APY"); see the percentage patterns
        # below. REGDD-STR-001 keys on LEX:APY text, not a rate entity.
        [{"LOWER": {"IN": ["rate", "rates"]}}, {"LOWER": "of"}, _NUM, _PCT],
        # "rate: X%" — colon instead of "of".
        [{"LOWER": {"IN": ["rate", "rates"]}}, {"TEXT": ":"}, _NUM, _PCT],
        # Postfix "X% rate". Adjacency keeps "4.50% APY rate-like copy"
        # out (any token between "%" and "rate" blocks the match), and
        # apr's higher priority still claims "% Annual Percentage Rate".
        [_NUM, _PCT, {"LOWER": {"IN": ["rate", "rates"]}}],
    ],
    "fee": [
        [{"TEXT": "$"}, _NUM, _ANY(2), {"LOWER": {"REGEX": r"^fees?$"}}],
        [{"LOWER": {"REGEX": r"^fees?$"}}, {"LOWER": "of"}, {"TEXT": "$"}, _NUM],
        [{"LOWER": {"IN": ["no", "zero"]}}, _ANY(1), {"LOWER": {"REGEX": r"^fees?$"}}],
        # "N dollars ... fee" — must outrank the bare "N dollars" amount
        # pattern (fee precedes amount in _PRIORITY, so the longer fee
        # span wins overlap resolution).
        [_NUM, _DOLLARS_WORD, _ANY(2), {"LOWER": {"REGEX": r"^fees?$"}}],
        # Rate-style recurring fee with no "fee" token: "$12/mo". The
        # optional trailing dot covers spaCy's abbreviation tokenization
        # of a sentence-final "Mo." (kept as one token, dot included).
        [{"TEXT": "$"}, _NUM, {"TEXT": "/"},
         {"LOWER": {"REGEX": r"^(mo|month|yr|year|wk|week)\.?$"}}],
    ],
    "time_period": [
        [_NUM, {"LOWER": {"IN": _TIME_UNIT_TOKENS}}],
        # Hyphenated form: spaCy splits "60-month" into ["60", "-",
        # "month"], so neither the spaced pattern above nor a single-token
        # regex fires — match the three-token sequence explicitly.
        [_NUM, {"TEXT": "-"}, {"LOWER": {"IN": _TIME_UNIT_TOKENS}}],
        [{"TEXT": {"REGEX": r"^\d+-(minute|hour|day|week|month|year)s?$"}}],
        # OCR-merged forms: a dropped space/hyphen fuses number and unit
        # into one token ("36months", "60month").
        [{"LOWER": {"REGEX": r"^\d+(minute|hour|day|week|month|year)s?$"}}],
        # Spelled-out numbers: "twelve months", "twenty-four months".
        [{"LOWER": {"IN": list(_WORD_NUMS)}}, {"LOWER": {"IN": _TIME_UNIT_TOKENS}}],
        [{"LOWER": {"IN": list(_TENS_WORDS)}}, {"TEXT": "-"},
         {"LOWER": {"IN": list(_ONES_WORDS)}}, {"LOWER": {"IN": _TIME_UNIT_TOKENS}}],
    ],
    "amount": [
        # $/€/£/₹/¥ prefix, optional magnitude word ("₹1.5 LAKH", "$75K").
        [_CUR_SYM, _NUM, _MAG_TOKEN],
        [_CUR_SYM, _NUM],
        # "Rs. 5,000" — rupee written as a code with an optional dot.
        [_CUR_CODE, {"TEXT": ".", "OP": "?"}, _NUM, _MAG_TOKEN],
        [_CUR_CODE, {"TEXT": ".", "OP": "?"}, _NUM],
        # Trailing code: "5,000 USD".
        [_NUM, _MAG_TOKEN, _CUR_CODE],
        [_NUM, _CUR_CODE],
        # Currency written out: "1,000 dollars". A "N dollars ... fee"
        # context is claimed by the higher-priority fee pattern instead.
        [_NUM, _DOLLARS_WORD],
    ],
    "percentage": [
        # Longer APY span wins over the bare "N %" span in overlap
        # resolution, so "4.50% APY" is one percentage entity whose
        # raw_text includes "APY" (matches the gold labeling convention).
        [_NUM, _PCT, {"LOWER": "apy"}],
        [_NUM, _PCT],
        # "percent" written out: "41 percent". "N percent APR" is claimed
        # by the higher-priority, longer apr pattern.
        [_NUM, _PERCENT_WORD],
    ],
}

# EntityRuler patterns for lexical (non-numeric) types.
_RULER_PATTERNS = [
    {"label": "superlative", "pattern": [{"LOWER": {"IN": [
        "lowest", "best", "highest", "fastest", "cheapest", "biggest",
        "largest", "leading", "top-rated", "unbeatable"]}}]},
    {"label": "superlative", "pattern": [{"TEXT": "#"}, {"TEXT": "1"}]},
    # spaCy splits "top-rated" into ["top", "-", "rated"], so the
    # single-token IN entry above never fires for it.
    {"label": "superlative",
     "pattern": [{"LOWER": "top"}, {"TEXT": "-"}, {"LOWER": "rated"}]},
    # OCR-dropped punctuation fuses hyphenated lexicals into one token.
    {"label": "superlative", "pattern": [{"LOWER": "toprated"}]},
    {"label": "optout_marker", "pattern": [{"LOWER": "optout"}]},
    {"label": "guarantee_term", "pattern": [{"LOWER": "riskfree"}]},
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

# --- OCR-noise repair variants (span-mapped) -------------------------
# OCR corrupts text three recoverable ways: glyph confusions (0/o,
# 1/l/I, 5/s, 8/B), dropped spaces (word-number merges: "a60-month",
# "16,300Usd"), and inserted spaces (word splits: "percen t",
# "guaran teed"). Each repair produces a variant text plus a char-level
# map back to the original, so any pattern match on a variant yields a
# valid span on the original text: raw_text is always sliced from the
# original, normalization reads the repaired variant. On clean text
# every repair is a no-op, so non-OCR inputs are undisturbed (the
# original text is always matched first and wins ties).
_LETTERIFY = {"0": "o", "1": "l", "5": "s", "8": "b"}
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

#: Words the split-rejoin repair may reassemble — the vocabulary of the
#: extraction patterns themselves (units, pattern keywords, lexicals).
_REPAIR_VOCAB = frozenset(
    w for w in (
        "percent apr apy annual percentage rate rates interest intro "
        "month months year years minute minutes hour hours day days "
        "week weeks fee fees dollar dollars usd amount reply stop "
        "unsubscribe optout sponsored partnership paid seen guaranteed "
        "guarantee riskfree lowest best highest fastest cheapest "
        "leading unbeatable toprated approval credit"
    ).split()
)


def _denoise(text: str) -> str:
    """Repair OCR digit-for-letter confusions inside wordish tokens
    (1:1 in length, so spans are shared with the input text)."""
    def fix(m: re.Match) -> str:
        tok = m.group(0)
        letters = sum(c.isalpha() for c in tok)
        digits = len(tok) - letters
        if letters > digits and any(c in _LETTERIFY for c in tok):
            return "".join(_LETTERIFY.get(c, c) for c in tok)
        return tok
    return _TOKEN_RE.sub(fix, text)


def _boundary_split(text: str, base_map: list[int]) -> tuple[str, list[int]]:
    """Insert a space at OCR-merge boundaries: letter->digit/$ and
    digit/%->letter runs (2+ letters, so magnitude suffixes like $75K
    stay whole). Returns (variant, map) where map[i] is the original
    index of variant char i."""
    chars: list[str] = []
    cmap: list[int] = []
    for i, ch in enumerate(text):
        prev = text[i - 1] if i else ""
        if prev and (
            (prev.isalpha() and (ch.isdigit() or ch == "$"))
            or ((prev.isdigit() or prev == "%") and ch.isalpha()
                and i + 1 < len(text) and text[i + 1].isalpha())
        ):
            chars.append(" ")
            cmap.append(base_map[i])
        chars.append(ch)
        cmap.append(base_map[i])
    return "".join(chars), cmap


def _rejoin_splits(text: str, base_map: list[int]) -> tuple[str, list[int]]:
    """Rejoin OCR-inserted splits: adjacent alphabetic fragments whose
    concatenation (pairs, then triples) is a pattern-vocabulary word are
    fused ("percen t" -> "percent"). Returns (variant, map)."""
    tokens = list(re.finditer(r"\S+", text))
    chars: list[str] = []
    cmap: list[int] = []
    pos = 0  # index into tokens
    last_end = 0

    def emit(start: int, end: int) -> None:
        for i in range(start, end):
            chars.append(text[i])
            cmap.append(base_map[i])

    while pos < len(tokens):
        joined = None
        for width in (3, 2):
            group = tokens[pos:pos + width]
            if len(group) == width and all(
                t.group(0).isalpha() for t in group
            ) and "".join(t.group(0) for t in group).lower() in _REPAIR_VOCAB:
                joined = group
                break
        if joined:
            emit(last_end, joined[0].start())
            for t in joined:  # copy fragments, skip the gaps between them
                emit(t.start(), t.end())
            last_end = joined[-1].end()
            pos += len(joined)
        else:
            emit(last_end, tokens[pos].end())
            last_end = tokens[pos].end()
            pos += 1
    emit(last_end, len(text))
    return "".join(chars), cmap


def _variants(text: str) -> list[tuple[str, list[int]]]:
    """(variant_text, char_map) list: original first, then OCR repairs.
    map[i] = index in the ORIGINAL text of variant char i; a span
    (s, e) on a variant maps to (map[s], map[e-1] + 1) on the original.
    """
    identity = list(range(len(text)))
    out = [(text, identity)]
    lett = _denoise(text)
    lett_map = identity
    if lett != text:
        out.append((lett, lett_map))
    split_text, split_map = _boundary_split(lett, lett_map)
    if split_text != lett:
        out.append((split_text, split_map))
    joined_text, joined_map = _rejoin_splits(lett, lett_map)
    if joined_text != lett:
        out.append((joined_text, joined_map))
    return out


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


def _apply_magnitude(base: float | None, raw: str) -> float | None:
    """Scale a base amount by a trailing magnitude word (K/M/B/LAKH/CR)."""
    if base is None:
        return None
    m = _MAG_RE.search(raw)
    if m:
        key = m.group(1).lower().rstrip("s")
        base *= _MAGNITUDES.get(key, 1.0)
    return base


def _normalize(label: str, raw: str) -> float | None:
    """Percent types -> the number; fee/amount -> USD; time -> days.

    None for non-numeric types, matching gold-label conventions.
    """
    if label in ("apr", "rate", "percentage"):
        return _first_number(raw)
    if label == "fee":
        if re.match(r"^\s*(no|zero)\b", raw, re.IGNORECASE):
            return 0.0
        return _apply_magnitude(_first_number(raw), raw)
    if label == "amount":
        return _apply_magnitude(_first_number(raw), raw)
    if label == "time_period":
        # Digits first; spelled-out numbers ("twelve months") as fallback.
        n = _first_number(raw)
        if n is None:
            n = _word_number(raw)
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

        # Multi-variant matching: the original text first, then the
        # OCR-repair variants; every variant match is mapped back to an
        # original-text span through its char map.
        candidates = []  # (orig_start, orig_end, label, variant_idx, norm_text)
        for vi, (src, cmap) in enumerate(_variants(text)):
            doc = nlp(src)
            spans = [(m_span.start_char, m_span.end_char,
                      nlp.vocab.strings[match_id])
                     for match_id, start, end in matcher(doc)
                     for m_span in (doc[start:end],)]
            spans += [(ent.start_char, ent.end_char, ent.label_)
                      for ent in doc.ents]
            for vs, ve, label in spans:
                if ve <= vs:
                    continue
                candidates.append((cmap[vs], cmap[ve - 1] + 1, label, vi,
                                   src[vs:ve]))

        # Greedy overlap resolution: type priority, then longer span,
        # then original-text matches before repaired-variant ones.
        candidates.sort(key=lambda c: (_PRIORITY.index(c[2]),
                                       -(c[1] - c[0]), c[0], c[3]))
        kept: list[tuple] = []
        for cand in candidates:
            start, end = cand[0], cand[1]
            if all(end <= k[0] or start >= k[1] for k in kept):
                kept.append(cand)
        kept.sort(key=lambda c: c[0])

        for start, end, label, _vi, norm_text in kept:
            raw = text[start:end]
            # Span-integrity invariant: the half-open char_span we emit
            # must be well-formed and non-empty within the segment text,
            # so downstream re-slicing text[start:end] always reproduces
            # raw_text. (A degenerate or out-of-bounds span is a bug.)
            # raw_text is ALWAYS the original text; normalization reads
            # the (possibly repaired) variant the pattern matched on.
            assert 0 <= start < end <= len(text), (start, end, len(text))
            n += 1
            entities.append({
                "entity_id": f"ent_{n}",
                "entity_type": label,
                "raw_text": raw,
                "normalized_value": _normalize(label, norm_text),
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
        ("percentage", "Earn 4.50% APY on every dollar."),  # APY -> percentage
        ("fee", "No annual fee, and a late fee of $29."),
        ("amount", "Borrow up to $40,000 today."),
        ("percentage", "Members save 72% on interest."),
        ("superlative", "The lowest rates in America."),
        ("endorsement_marker", "#ad Paid partnership with FinCo."),
        ("optout_marker", "Reply STOP to unsubscribe."),
        ("guarantee_term", "Guaranteed approval, completely risk-free."),
        ("time_period", "Approved in 5 minutes with a 60-month term."),
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

"""Reproducible synthetic marketing-asset generator.

Assembles labeled, ``schema.AssetRepresentation``-shaped ads from
role-tagged segment templates. Surface strings come from *general*
marketing/regulatory phrasing parameterized by randomized values — they
are not copied from the gold/silver corpora, so a model that scores well
on this corpus has generalized, not memorized.

This generator is deliberately built to stress patterns the current
deterministic extractor was NOT written against. Four expansion
dimensions, each seeded and programmatic:

  1. Phrasing families per entity type — alternative APR/fee/rate/amount
     phrasings drawn from real fintech-ad conventions (spelled-out
     "Annual Percentage Rate", "intro APR", "X percent", "$X monthly
     fee", "1,000 dollars", "X% rate", magnitude suffixes, USD codes).
     Every emitted entity carries a ``phrasing_family`` tag so the eval
     can bucket recall by (entity_type, phrasing_family).
  2. Sentence-position / case variation — entity mid-sentence,
     sentence-initial, bare fragment, ALL CAPS, Title Case.
  3. OCR-noise mode — span-aware character corruption (1/l/I, 0/O, rn/m
     confusions; dropped punctuation; merged/split tokens) calibrated to
     ``synth/ocr_eval.py``'s measured error level. Clean and noisy copies
     carry the SAME labels: entity spans are remapped, digit cores are
     protected so ``normalized_value`` stays valid, and matching is done
     value-mode.
  4. Negative examples — financial-sounding assets with NO extractable
     entities, to measure false positives.

Ground truth is emitted alongside the text:
  * entities with exact half-open char spans and the normalized values
    the deterministic extractor is contracted to produce;
  * claim candidates (whole-segment spans) for every claim a reasonable
    reviewer would examine;
  * routing (product_type + frameworks) from the settled deterministic
    policy.

Determinism: ``generate_corpus(n, seed)`` is a pure function of its
arguments. The CLI writes a train/val split plus an optional
OCR-noise-augmented robustness split.

Usage:
    python -m synth.generator --n 400 --seed 7 --out data/synth
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys

# ---------------------------------------------------------------------------
# Value generators. Each returns (raw_text, entity_type, normalized_value,
# phrasing_family) with the SAME normalization conventions the deterministic
# extractor is contracted to produce (percent/apr/rate -> the number;
# fee/amount -> USD; time_period -> days). The phrasing_family tag names the
# surface convention so the eval can rank (entity_type, family) recall gaps.
# Values are chosen so a correct extractor SHOULD emit the labeled entity;
# where a family is beyond the current patterns, the eval surfaces the gap.
# ---------------------------------------------------------------------------

_MONTHS = 30.4375
_YEARS = 365.25

# Spelled-out small numbers for the "no digits" families (extractor is
# digit-driven, so these probe word-number coverage).
_NUM_WORDS = {"six": 6, "twelve": 12, "twenty-four": 24, "thirty-six": 36,
              "sixty": 60}


def _money(rng: random.Random, lo: int, hi: int, step: int = 50) -> int:
    return rng.randrange(lo, hi + 1, step)


def gen_apr(rng):
    """APR phrasing families. value = the percent number."""
    v = round(rng.uniform(2.99, 29.99), 2)
    fam = rng.choice(["apr_std", "apr_std", "apr_spelled_out",
                      "apr_prefix_of", "apr_word_pct"])
    if fam == "apr_std":
        raw = f"{v:.2f}% APR"                       # baseline (matches)
    elif fam == "apr_spelled_out":
        raw = f"{v:.2f}% Annual Percentage Rate"    # no 'APR' token
    elif fam == "apr_prefix_of":
        raw = f"APR of {v:.2f}%"                    # 'APR' before the number
    else:  # apr_word_pct — 'percent' word instead of '%'
        raw = f"{v:.2f} percent APR"
    return (raw, "apr", v, fam)


def gen_intro_apr(rng):
    """'0% intro APR' — 'intro' sits between '%' and 'APR'. value = 0."""
    return ("0% intro APR", "apr", 0.0, "apr_intro")


def gen_apy(rng):
    # An APY-stated yield is a *percentage* whose span includes "APY".
    v = round(rng.uniform(0.40, 5.50), 2)
    return (f"{v:.2f}% APY", "percentage", v, "pct_apy")


def gen_pct(rng):
    """Bare-percentage families. value = the number."""
    fam = rng.choice(["pct_symbol", "pct_symbol", "pct_decimal",
                      "pct_word_percent"])
    if fam == "pct_symbol":
        v = rng.randint(1, 90)
        return (f"{v}%", "percentage", float(v), fam)
    if fam == "pct_decimal":
        v = round(rng.uniform(1.5, 12.0), 2)
        return (f"{v:.2f}%", "percentage", v, fam)
    v = rng.randint(1, 90)                          # 'percent' word, no '%'
    return (f"{v} percent", "percentage", float(v), "pct_word_percent")


def gen_rate(rng):
    """Interest-rate families (type 'rate'). value = the number.

    The extractor only recognizes 'rate(s) of X%'; 'rate: X%' and
    'X% rate' denote the same fact but are unhandled — a labeler marks
    them 'rate', so they surface as rate recall / percentage-confusion
    gaps.
    """
    v = round(rng.uniform(1.5, 12.0), 2)
    fam = rng.choice(["rate_of", "rate_interest_of", "rate_colon",
                      "rate_postfix"])
    if fam == "rate_of":
        raw = f"rate of {v:.2f}%"
    elif fam == "rate_interest_of":
        raw = f"interest rate of {v:.2f}%"
    elif fam == "rate_colon":
        raw = f"rate: {v:.2f}%"
    else:
        raw = f"{v:.2f}% rate"
    return (raw, "rate", v, fam)


def gen_amount(rng):
    """Currency-amount families. value = USD."""
    v = _money(rng, 500, 75000, 100)
    fam = rng.choice(["amt_symbol_comma", "amt_symbol_plain", "amt_usd_code",
                      "amt_dollars_word", "amt_k_suffix"])
    if fam == "amt_symbol_comma":
        return (f"${v:,}", "amount", float(v), fam)
    if fam == "amt_symbol_plain":
        return (f"${v}", "amount", float(v), fam)
    if fam == "amt_usd_code":
        return (f"{v:,} USD", "amount", float(v), fam)
    if fam == "amt_dollars_word":                   # 'dollars' is not a code
        return (f"{v:,} dollars", "amount", float(v), fam)
    k = v / 1000.0                                  # '$75K' magnitude suffix
    kraw = f"{k:g}"
    return (f"${kraw}K", "amount", float(v), "amt_k_suffix")


def gen_small_amount(rng):
    v = _money(rng, 15, 900, 5)
    if rng.random() < 0.5:
        return (f"${v:,}", "amount", float(v), "amt_symbol_comma")
    return (f"{v:,} dollars", "amount", float(v), "amt_dollars_word")


def gen_fee(rng):
    """Fee families. value = USD (0.0 for a waived fee)."""
    fam = rng.choice(["fee_no_annual", "fee_dollar_annual", "fee_of",
                      "fee_monthly_dollar", "fee_slash_month",
                      "fee_dollars_word"])
    if fam == "fee_no_annual":
        return (rng.choice(["No annual fee", "Zero annual fee"]), "fee", 0.0, fam)
    v = _money(rng, 15, 199, 1)
    if fam == "fee_dollar_annual":
        return (f"${v} annual fee", "fee", float(v), fam)
    if fam == "fee_of":
        return (f"annual fee of ${v}", "fee", float(v), fam)
    if fam == "fee_monthly_dollar":
        return (f"${v} monthly fee", "fee", float(v), fam)
    if fam == "fee_slash_month":                    # no 'fee' token at all
        return (f"${v}/mo", "fee", float(v), fam)
    return (f"{v} dollars annual fee", "fee", float(v), "fee_dollars_word")


def gen_time(rng):
    """Duration families. value = days."""
    fam = rng.choice(["time_hyphen_month", "time_spaced_month", "time_years",
                      "time_hyphen_year", "time_word_number"])
    if fam == "time_word_number":                   # 'twelve months', no digit
        word, n = rng.choice(list(_NUM_WORDS.items()))
        return (f"{word} months", "time_period", n * _MONTHS, fam)
    if fam in ("time_years", "time_hyphen_year"):
        n = rng.choice([2, 3, 5, 7, 10, 15, 30])
        raw = f"{n} years" if fam == "time_years" else f"{n}-year"
        return (raw, "time_period", n * _YEARS, fam)
    n = rng.choice([6, 12, 18, 24, 36, 48, 60, 72, 84])
    raw = f"{n}-month" if fam == "time_hyphen_month" else f"{n} months"
    return (raw, "time_period", n * _MONTHS, fam)


def gen_minutes(rng):
    n = rng.choice([2, 3, 5, 10, 15])
    return (f"{n} minutes", "time_period", n * (1 / 1440), "time_minutes")


# Lexical (non-numeric) entities: (raw, type, None, family)
_SUPERLATIVES = ["lowest", "best", "highest", "fastest", "cheapest",
                 "leading", "unbeatable", "top-rated"]
_GUARANTEE = ["guaranteed", "risk-free", "no risk", "guarantee"]
_ENDORSE = ["#ad", "sponsored", "paid partnership", "as seen on"]
_OPTOUT = ["unsubscribe", "opt-out", "reply STOP"]


def _lex(word, etype):
    def g(rng):
        return (word, etype, None, "lexical")
    return g


# ---------------------------------------------------------------------------
# Segment assembly with exact span tracking + position/case styling
# ---------------------------------------------------------------------------

# A "part" is either a literal string or a callable(rng) -> value tuple.
Part = object


def _build_segment(rng, parts):
    """Return (text, [entity dicts without ids]) with exact char spans."""
    text = ""
    ents = []
    for part in parts:
        if isinstance(part, str):
            text += part
        else:
            raw, etype, nv, family = part(rng)
            start = len(text)
            text += raw
            ents.append({
                "entity_type": etype, "raw_text": raw,
                "normalized_value": nv,
                "char_span": {"start": start, "end": start + len(raw)},
                "phrasing_family": family,
            })
    return text, ents


def _restyle(rng, text, ents):
    """Apply a length-preserving case style to a segment, keeping spans
    valid by re-slicing each entity's raw_text from the styled text.

    ``str.upper``/``str.title`` are 1:1 on the ASCII we generate, so char
    offsets and the labeled ``normalized_value`` are unchanged; only the
    surface case differs (a real stressor for lexical patterns and a
    no-op the numeric patterns should survive).
    """
    style = rng.choices(["asis", "upper", "title"], weights=[0.7, 0.15, 0.15])[0]
    if style != "asis":
        text = text.upper() if style == "upper" else text.title()
        for e in ents:
            s, en = e["char_span"]["start"], e["char_span"]["end"]
            e["raw_text"] = text[s:en]
    return text, style


# ---------------------------------------------------------------------------
# Template bank. Each entry: a function(rng) -> list of segment specs
# (role, parts, [declared claim_types]). Templates encode GENERAL patterns;
# variety comes from value randomization, phrasing families, position/case
# styling, template choice, and optional segments.
# ---------------------------------------------------------------------------

_TILA_PRODUCTS = {"credit_card", "personal_loan", "mortgage", "auto_loan", "bnpl"}
_ECOA_PRODUCTS = _TILA_PRODUCTS
_CREDIT_LIKE = _TILA_PRODUCTS | {"credit_repair"}

_STATES = ["US-CA", "US-NY", "US-TX", "US-FL", "US-WA", "US-IL"]

# Mirror of nlp.routing_lexicon.MINI_TCPA_STATES for ground-truth
# routing (kept literal so the generator stays dependency-light; the
# consistency test in tests/test_synth.py guards drift).
_MINI_TCPA_STATES = frozenset({
    "US-FL", "US-OK", "US-WA", "US-AZ", "US-CT", "US-MD", "US-NJ",
    "US-GA", "US-TX", "US-VA",
})

_FDIC_LEGAL = ["Member FDIC", "Member FDIC.", "Bank, N.A. Member FDIC",
               "FDIC-insured"]
_PLAIN_LEGAL = ["NMLS #123456", "Equal Housing Lender", "© 2026 Acme Financial",
                "All rights reserved"]


def _headline_pricing(rng, product):
    """A headline carrying a pricing entity, in a varied sentence position.

    Position families: mid-sentence, sentence-initial, and bare fragment —
    so the same entity is exercised in different surrounding context.
    """
    choices = []
    if product in _TILA_PRODUCTS:
        pname = product.replace("_", " ")
        choices += [
            # mid-sentence, with a superlative
            (["Get a ", _lex(rng.choice(_SUPERLATIVES), "superlative"),
              " ", gen_apr, " on your new ", pname, "!"],
             ["pricing", "performance"]),
            # sentence-initial entity
            ([gen_apr, f" on every new {pname} — apply today."], ["pricing"]),
            # bare fragment
            ([gen_apr], ["pricing"]),
            # intro-APR promo (entity + a duration entity)
            (["Enjoy ", gen_intro_apr, " for the first ", gen_time,
              f" on a {pname}."], ["pricing"]),
            # 'rate' phrasing family
            ([f"{pname.capitalize()} at a ", gen_rate, " with autopay."],
             ["pricing"]),
        ]
    if product == "deposit_account":
        choices += [
            (["Earn ", gen_apy, " on every dollar."], ["pricing"]),
            ([gen_apy, " APY — open a high-yield savings account."], ["pricing"]),
        ]
    if product == "investment":
        choices += [
            (["Grow your investment portfolio with ", gen_pct,
              " annual returns."], ["pricing", "performance"]),
            (["Target returns between ", gen_pct, " and ", gen_pct,
              " per year."], ["pricing", "performance"]),  # range family
        ]
    if product == "crypto":
        choices += [
            (["Buy crypto and grow your portfolio with ", gen_pct,
              " annual returns."], ["pricing", "performance"]),
        ]
    if product == "credit_repair":
        choices += [
            (["Fix your credit fast — ", _lex("guaranteed", "guarantee_term"),
              " results."], ["guarantee", "performance"]),
        ]
    if product == "insurance":
        choices += [
            (["Save ", gen_pct, " on your insurance premium today."],
             ["pricing", "performance"]),
            (["Rates starting at a ", gen_rate, " on select policies."],
             ["pricing"]),
        ]
    if not choices:
        choices = [(["Save ", gen_pct, " with ", product.replace("_", " "), "."],
                    ["pricing", "performance"])]
    return rng.choice(choices)


def _body_specs(rng, product):
    specs = []
    if product in _CREDIT_LIKE:
        specs.append(("body",
                      ["Borrow up to ", gen_amount, " with a ", gen_time,
                       " term."], ["pricing"]))
    if product == "deposit_account":
        specs.append(("body",
                      ["No minimum balance and ", gen_fee, "."], ["pricing"]))
    if product == "credit_card" and rng.random() < 0.5:
        specs.append(("body",
                      ["Just a ", gen_fee, " and earn up to ", gen_pct,
                       " cash back."], ["pricing"]))
    # Extra sampling for the rarer rate/fee phrasing families, so the
    # (entity_type, phrasing_family) gap table has measurable support
    # for every family (rate_postfix / fee_dollars_word were previously
    # below the table's min_support in a 150-asset val split).
    if product in _TILA_PRODUCTS and rng.random() < 0.3:
        specs.append(("body",
                      ["Lock in a ", gen_rate, " when you enroll in autopay."],
                      ["pricing"]))
    if product in ("credit_card", "bnpl", "personal_loan") and rng.random() < 0.5:
        specs.append(("body", ["Plus ", gen_fee, "."], []))
    if rng.random() < 0.5:
        specs.append(("body",
                      ["Approved in ", gen_minutes,
                       " — it's fast and effortless."], ["performance"]))
    if rng.random() < 0.4:
        specs.append(("body",
                      ["We beat every other ",
                       "bank" if product == "deposit_account" else "lender",
                       " on price."], ["comparative"]))
    return specs


def _cta_spec(rng):
    return ("cta", [rng.choice(
        ["Apply now", "Get started", "Sign up today", "Open an account",
         "Check your rate", "Learn more"])], [])


def _disclosure_spec(rng, product):
    parts = ["APY accurate as of 06/01/2026. " if product == "deposit_account"
             else "Rates may change. "]
    if product in _TILA_PRODUCTS:
        parts += ["Example based on a ", gen_amount, " loan at ", gen_apr,
                  " over a ", gen_time,
                  " term. Subject to credit approval. Your actual rate may vary."]
    else:
        parts += ["Terms and conditions apply. Subject to approval. "
                  "See site for details."]
    return ("disclosure", parts, [])


def _legal_spec(rng, product, force_fdic):
    if force_fdic or (product == "deposit_account" and rng.random() < 0.9):
        return ("legal", [rng.choice(_FDIC_LEGAL)], [])
    return ("legal", [rng.choice(_PLAIN_LEGAL)], [])


def _endorsement_prefix(rng):
    marker = rng.choice(_ENDORSE)
    etype = "endorsement_marker"
    return ("body", [_lex(marker, etype), " — real member results."],
            ["endorsement"])


def _optout_spec(rng):
    return ("fine_print", [_lex(rng.choice(_OPTOUT), "optout_marker"),
                           " to stop receiving these emails."], [])


# ---------------------------------------------------------------------------
# Negative examples: financial-sounding brand copy with NO extractable
# entities (no numbers, %, $, superlatives, guarantees, endorsement/optout
# markers, or numbered durations). Used to measure false positives.
# ---------------------------------------------------------------------------

_NEG_HEADLINES = [
    "Banking that moves at your pace.",
    "Your financial journey starts here.",
    "Money management, reimagined.",
    "A smarter way to bank.",
    "Built around what matters to you.",
]
_NEG_BODIES = [
    "Join a community that puts members first.",
    "Secure, simple, and made for the way you live.",
    "Move money with confidence, wherever you are.",
    "Real people and real support, whenever you need it.",
    "Designed to help you reach what comes next.",
    "Peace of mind, built into everything we do.",
]
_NEG_CTAS = ["Learn more", "Get started", "Explore accounts", "See how it works"]


def _negative_asset(rng: random.Random, idx: int) -> dict:
    """A schema-valid asset with zero extractable entities."""
    product = rng.choice(_PRODUCTS)
    specs = [("headline", [rng.choice(_NEG_HEADLINES)], [])]
    for _ in range(rng.randint(1, 3)):
        specs.append(("body", [rng.choice(_NEG_BODIES)], []))
    specs.append(("cta", [rng.choice(_NEG_CTAS)], []))
    specs.append(("legal", [rng.choice(_PLAIN_LEGAL)], []))

    segments = []
    for i, (role, parts, _decl) in enumerate(specs, start=1):
        text, _ = _build_segment(rng, parts)
        segments.append({
            "segment_id": f"seg_{i}", "text": text, "role": role,
            "source": "text", "bbox": None, "ocr_confidence": None,
        })
    # Ground truth is what a correct router can extract from the
    # creative: negative copy names no product and trips no trigger, so
    # the intended routing is the FTC baseline with product unknown.
    # (The sampled ``product`` only flavors nothing here — negatives
    # measure false-positive routing, not product recall.)
    return {
        "asset_id": f"synth_{idx:05d}",
        "segments": segments,
        "entities": [],
        "claim_candidates": [],
        "cv_findings": [],
        "semantic_signals": [],
        "routing": {
            "product_type": "unknown",
            "frameworks": ["FTC"],
            "signal": "synthetic negative (no extractable product/triggers)",
        },
        "target_jurisdictions": [],
        "negative": True,
        "provenance": {
            "cv_version": "synth", "nlp_version": "synth",
            "ruleset_hash": "synth", "timestamp": "2026-01-01T00:00:00Z",
        },
    }


# ---------------------------------------------------------------------------
# Routing policy (ground truth) — the settled deterministic policy.
# ---------------------------------------------------------------------------

def _intended_routing(product, has_rate, fdic, endorsement, optout, states,
                      nmls_wording=False):
    fw = ["FTC"]
    if product == "deposit_account":
        fw += ["Reg_DD", "CFPB"]
    elif product in _TILA_PRODUCTS or has_rate:
        fw += ["TILA", "CFPB"]
    elif product == "credit_repair":
        fw += ["CFPB"]
    if product in _ECOA_PRODUCTS:
        fw.append("ECOA")
    if fdic:
        fw.append("FDIC")
    if product in ("investment", "crypto"):
        fw += ["SEC", "FINRA"]
    if optout:
        fw += ["CAN-SPAM", "TCPA"]
    if states:
        fw.append("STATE_UDAP")
    # Coverage-matrix policy (ruleset 1.4.0 routing triggers).
    if product == "mortgage":
        fw += ["Reg_N", "NMLS"]
    if product == "crypto":
        fw.append("CFTC_NFA")
    if nmls_wording:
        fw.append("NMLS")
    if optout and set(states) & _MINI_TCPA_STATES:
        fw.append("MINI_TCPA")
    return list(dict.fromkeys(fw))


# ---------------------------------------------------------------------------
# Asset assembly
# ---------------------------------------------------------------------------

_PRODUCTS = ["credit_card", "personal_loan", "mortgage", "auto_loan", "bnpl",
             "deposit_account", "investment", "crypto", "insurance",
             "credit_repair"]

_SKIP_CLAIM_ROLES = {"disclosure", "legal", "fine_print"}
_STYLE_ROLES = {"headline", "body"}  # roles that get position/case styling

_NEGATIVE_FRAC = 0.15


def generate_asset(rng: random.Random, idx: int) -> dict:
    if rng.random() < _NEGATIVE_FRAC:
        return _negative_asset(rng, idx)

    product = rng.choice(_PRODUCTS)
    force_fdic = product == "deposit_account"

    specs = []  # (role, parts, claim_types)
    hp_parts, hp_claims = _headline_pricing(rng, product)
    specs.append(("headline", hp_parts, hp_claims))
    specs += _body_specs(rng, product)

    endorsement = rng.random() < 0.3
    if endorsement:
        specs.append(_endorsement_prefix(rng))

    optout = rng.random() < 0.25
    if optout:
        specs.append(_optout_spec(rng))

    if rng.random() < 0.85:
        specs.append(_cta_spec(rng))
    if rng.random() < 0.9:
        specs.append(_disclosure_spec(rng, product))
    specs.append(_legal_spec(rng, product, force_fdic))

    # Build segments/entities with running ids and exact spans.
    segments, entities, claims = [], [], []
    en = cn = 0
    for i, (role, parts, decl_claims) in enumerate(specs, start=1):
        text, seg_ents = _build_segment(rng, parts)
        if role in _STYLE_ROLES:
            text, _style = _restyle(rng, text, seg_ents)
        seg_id = f"seg_{i}"
        segments.append({
            "segment_id": seg_id, "text": text, "role": role,
            "source": "text", "bbox": None, "ocr_confidence": None,
        })
        seg_entity_ids = []
        for e in seg_ents:
            en += 1
            e_id = f"ent_{en}"
            e.update({"entity_id": e_id, "segment_id": seg_id})
            entities.append(e)
            seg_entity_ids.append(e_id)

        # Claim ground truth: entity-driven pricing + declared claim types,
        # never on boilerplate roles.
        if role not in _SKIP_CLAIM_ROLES:
            ctypes = set(decl_claims)
            if any(e["entity_type"] in ("apr", "rate", "fee", "amount", "percentage")
                   for e in seg_ents):
                ctypes.add("pricing")
            for ct in sorted(ctypes):
                cn += 1
                claims.append({
                    "claim_id": f"clm_{cn}", "claim_type": ct, "text": text,
                    "segment_id": seg_id,
                    "char_span": {"start": 0, "end": len(text)},
                    "entity_ids": list(seg_entity_ids), "pattern_id": None,
                })

    full_text = " ".join(s["text"] for s in segments)
    fdic = bool(re.search(r"\bfdic\b|federally insured", full_text, re.I))
    nmls_wording = bool(re.search(r"\bnmls\b", full_text, re.I))
    has_rate = any(e["entity_type"] in ("apr", "rate") for e in entities)
    states = [rng.choice(_STATES)] if rng.random() < 0.35 else []
    frameworks = _intended_routing(product, has_rate, fdic, endorsement,
                                   optout, states,
                                   nmls_wording=nmls_wording)

    return {
        "asset_id": f"synth_{idx:05d}",
        "segments": segments,
        "entities": entities,
        "claim_candidates": claims,
        "cv_findings": [],
        "semantic_signals": [],
        "routing": {
            "product_type": product,
            "frameworks": frameworks,
            "signal": f"synthetic ground truth for {product}",
        },
        "target_jurisdictions": states,
        "provenance": {
            "cv_version": "synth", "nlp_version": "synth",
            "ruleset_hash": "synth", "timestamp": "2026-01-01T00:00:00Z",
        },
    }


def generate_corpus(n: int, seed: int = 0) -> list[dict]:
    """Deterministic list of ``n`` synthetic AssetRepresentation dicts."""
    rng = random.Random(seed)
    return [generate_asset(rng, i) for i in range(n)]


# ---------------------------------------------------------------------------
# OCR-noise augmentation (robustness split). Corrupts SEGMENT TEXT with a
# span-aware walk so entity LABELS survive: digit cores inside entity spans
# are protected (normalized_value stays valid), spans are remapped through
# the corruption, and letters/punctuation/spacing are degraded to model
# real OCR errors. The clean and noisy copies therefore carry the SAME
# labels and are scored value-mode.
#
# Rates are calibrated to synth/ocr_eval.py (PaddleOCR, raw variant):
# clean synthetic renders OCR at char_sim ~1.00 / word_recall ~1.00, while
# real gold screenshots measure char_sim ~0.67 / word_recall ~0.99 — i.e.
# tokens mostly survive but characters are heavily perturbed. This mode
# reproduces that regime (token-preserving character corruption) instead of
# the clean-render fidelity the synthetic pipeline would otherwise show.
# ---------------------------------------------------------------------------

_SUB = {"o": "0", "O": "0", "0": "O", "l": "1", "I": "1", "1": "l",
        "i": "l", "S": "5", "5": "S", "B": "8", "8": "B", "s": "5"}
_PUNCT = set(",.:;!-/")


def _noise_segment(rng, text, ents, sub_rate=0.10, punct_drop=0.35,
                   space_drop=0.15, split_rate=0.03):
    """Corrupt ``text`` and return (new_text, new_ents) with remapped spans.

    Digit/comma/period characters that fall inside an entity span are held
    fixed so the labeled numeric value remains recoverable; everything else
    is subject to confusion substitution, punctuation dropping, token
    merges (dropped spaces), token splits (inserted spaces), and the rn<->m
    OCR confusion.
    """
    protected = [False] * len(text)
    for e in ents:
        s, en = e["char_span"]["start"], e["char_span"]["end"]
        for i in range(s, en):
            if text[i].isdigit() or text[i] in ".,":
                protected[i] = True

    out = []
    # offset_map[i] = index in `out` where original char i begins.
    offset_map = [0] * (len(text) + 1)
    i = 0
    while i < len(text):
        offset_map[i] = _cur_len(out)
        ch = text[i]
        # rn <-> m confusion at token level (unprotected only).
        if not protected[i] and ch == "m" and rng.random() < sub_rate:
            out.append("rn")
            i += 1
            continue
        if (not protected[i] and ch == "r" and i + 1 < len(text)
                and text[i + 1] == "n" and not protected[i + 1]
                and rng.random() < sub_rate):
            out.append("m")
            offset_map[i + 1] = _cur_len(out)  # both map into the merged char
            i += 2
            continue
        if protected[i]:
            out.append(ch)
        elif ch == " ":
            if rng.random() >= space_drop:          # else drop -> token merge
                out.append(ch)
        elif ch in _PUNCT and rng.random() < punct_drop:
            pass                                     # drop punctuation
        elif ch in _SUB and rng.random() < sub_rate:
            out.append(_SUB[ch])
        else:
            out.append(ch)
            if ch != " " and rng.random() < split_rate:
                out.append(" ")                      # token split
        i += 1
    offset_map[len(text)] = _cur_len(out)
    new_text = "".join(out)

    new_ents = []
    for e in ents:
        s, en = e["char_span"]["start"], e["char_span"]["end"]
        ns, ne = offset_map[s], offset_map[en]
        if not (0 <= ns < ne <= len(new_text)):
            continue                                 # span collapsed; drop
        ne2 = e.copy()
        ne2["char_span"] = {"start": ns, "end": ne}
        ne2["raw_text"] = new_text[ns:ne]
        new_ents.append(ne2)
    return new_text, new_ents


def _cur_len(chunks) -> int:
    return sum(len(c) for c in chunks)


def augment_ocr_noise(asset: dict, rng: random.Random) -> dict:
    """Return an OCR-noised copy of ``asset`` with valid, remapped labels.

    Segment text is corrupted span-aware; entity spans/raw_text are
    remapped (normalized_value preserved); claim spans are reset to the
    new full-segment span; routing/roles/claim-types are unchanged.
    """
    a = json.loads(json.dumps(asset))
    a["asset_id"] = asset["asset_id"] + "_noisy"
    ents_by_seg: dict = {}
    for e in a["entities"]:
        ents_by_seg.setdefault(e["segment_id"], []).append(e)

    new_entities = []
    for s in a["segments"]:
        seg_ents = ents_by_seg.get(s["segment_id"], [])
        new_text, new_ents = _noise_segment(rng, s["text"], seg_ents)
        s["text"] = new_text
        new_entities.extend(new_ents)
    a["entities"] = new_entities

    for c in a["claim_candidates"]:
        seg = next(s for s in a["segments"] if s["segment_id"] == c["segment_id"])
        c["text"] = seg["text"]
        c["char_span"] = {"start": 0, "end": len(seg["text"])}
    return a


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _validate(assets: list[dict]) -> None:
    try:
        import schema
    except Exception:
        return
    for a in assets:
        schema.AssetRepresentation.model_validate(a)


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a synthetic asset corpus.")
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--val-frac", type=float, default=0.25)
    ap.add_argument("--out", default="data/synth")
    ap.add_argument("--noise", action="store_true",
                    help="also emit an OCR-noise robustness split")
    args = ap.parse_args()

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    corpus = generate_corpus(args.n, args.seed)
    _validate(corpus)

    n_val = int(round(args.n * args.val_frac))
    val, train = corpus[:n_val], corpus[n_val:]
    splits = {"train": train, "val": val}
    if args.noise:
        rng = random.Random(args.seed + 1)
        splits["val_noisy"] = [augment_ocr_noise(a, rng) for a in val]
        _validate(splits["val_noisy"])

    for name, assets in splits.items():
        d = os.path.join(args.out, name)
        os.makedirs(d, exist_ok=True)
        for a in assets:
            with open(os.path.join(d, f"{a['asset_id']}.json"), "w") as f:
                json.dump(a, f, indent=2)
        print(f"{name}: {len(assets)} assets -> {d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

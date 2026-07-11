"""Reproducible synthetic marketing-asset generator.

Assembles labeled, ``schema.AssetRepresentation``-shaped ads from
role-tagged segment templates. Surface strings come from *general*
marketing/regulatory phrasing parameterized by randomized values — they
are not copied from the gold/silver corpora, so a model that scores well
on this corpus has generalized, not memorized.

Ground truth is emitted alongside the text:
  * entities with exact half-open char spans and the normalized values
    the deterministic extractor is contracted to produce;
  * claim candidates (whole-segment spans) for every claim a reasonable
    reviewer would examine — entity-driven pricing plus template-declared
    claim types;
  * routing (product_type + frameworks) from the settled deterministic
    policy, so routing scoring measures the classifier, not a moving
    target.

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
# Value generators — each returns (raw_text, entity_type, normalized_value)
# with the SAME normalization conventions the deterministic extractor uses
# (percent/apr -> the number; fee/amount -> USD; time_period -> days).
# ---------------------------------------------------------------------------

_MONTHS = 30.4375


def _money(rng: random.Random, lo: int, hi: int, step: int = 50) -> int:
    return rng.randrange(lo, hi + 1, step)


def gen_apr(rng):
    v = round(rng.uniform(2.99, 29.99), 2)
    return (f"{v:.2f}% APR", "apr", v)


def gen_apy(rng):
    # An APY-stated yield is a *percentage* whose span includes "APY".
    v = round(rng.uniform(0.40, 5.50), 2)
    return (f"{v:.2f}% APY", "percentage", v)


def gen_pct(rng):
    v = rng.randint(1, 90)
    return (f"{v}%", "percentage", float(v))


def gen_rate_of(rng):
    v = round(rng.uniform(1.5, 12.0), 2)
    return (f"rate of {v:.2f}%", "rate", v)


def gen_amount(rng):
    v = _money(rng, 500, 75000, 100)
    return (f"${v:,}", "amount", float(v))


def gen_small_amount(rng):
    v = _money(rng, 15, 900, 5)
    return (f"${v:,}", "amount", float(v))


def gen_fee(rng):
    form = rng.random()
    if form < 0.4:
        return (rng.choice(["No annual fee", "Zero annual fee"]), "fee", 0.0)
    v = _money(rng, 15, 199, 1)
    if form < 0.7:
        return (f"${v} annual fee", "fee", float(v))
    return (f"annual fee of ${v}", "fee", float(v))


def gen_time(rng):
    n = rng.choice([6, 12, 18, 24, 36, 48, 60, 72, 84])
    unit = rng.choice(["month", "months"])
    if rng.random() < 0.5:
        raw = f"{n}-month"
    else:
        raw = f"{n} {unit}"
    return (raw, "time_period", n * _MONTHS)


def gen_minutes(rng):
    n = rng.choice([2, 3, 5, 10, 15])
    return (f"{n} minutes", "time_period", n * (1 / 1440))


# Lexical (non-numeric) entities: (raw, type, None)
_SUPERLATIVES = ["lowest", "best", "highest", "fastest", "cheapest",
                 "leading", "unbeatable", "top-rated"]
_GUARANTEE = ["guaranteed", "risk-free", "no risk", "guarantee"]
_ENDORSE = ["#ad", "sponsored", "paid partnership", "as seen on"]
_OPTOUT = ["unsubscribe", "opt-out", "reply STOP"]


def _lex(word, etype):
    def g(rng):
        return (word, etype, None)
    return g


# ---------------------------------------------------------------------------
# Segment assembly with exact span tracking
# ---------------------------------------------------------------------------

# A "part" is either a literal string or a callable(rng) -> (raw, type, nv).
Part = object


def _build_segment(rng, parts):
    """Return (text, [entity dicts without ids]) with exact char spans."""
    text = ""
    ents = []
    for part in parts:
        if isinstance(part, str):
            text += part
        else:
            raw, etype, nv = part(rng)
            start = len(text)
            text += raw
            ents.append({
                "entity_type": etype, "raw_text": raw,
                "normalized_value": nv,
                "char_span": {"start": start, "end": start + len(raw)},
            })
    return text, ents


# ---------------------------------------------------------------------------
# Template bank. Each entry: a function(rng) -> list of segment specs
# (role, parts, [declared claim_types]). Optional segments are chosen by
# the assembler. Templates encode GENERAL patterns; variety comes from
# value randomization + template choice + optional segments.
# ---------------------------------------------------------------------------

_TILA_PRODUCTS = {"credit_card", "personal_loan", "mortgage", "auto_loan", "bnpl"}
_ECOA_PRODUCTS = _TILA_PRODUCTS
_CREDIT_LIKE = _TILA_PRODUCTS | {"credit_repair"}

_STATES = ["US-CA", "US-NY", "US-TX", "US-FL", "US-WA", "US-IL"]

_FDIC_LEGAL = ["Member FDIC", "Member FDIC.", "Bank, N.A. Member FDIC",
               "FDIC-insured"]
_PLAIN_LEGAL = ["NMLS #123456", "Equal Housing Lender", "© 2026 Acme Financial",
                "All rights reserved"]


def _headline_pricing(rng, product):
    """A headline that carries a pricing entity + optional superlative."""
    choices = []
    if product in _TILA_PRODUCTS:
        # Real ads name (or strongly imply) the product somewhere; keep it
        # in the headline so ground truth is fair to a text classifier.
        pname = product.replace("_", " ")
        choices += [
            (["Get a ", _lex(rng.choice(_SUPERLATIVES), "superlative"),
              " ", gen_apr, " on your new ", pname, "!"],
             ["pricing", "performance"]),
            ([f"{pname.capitalize()} rates from ", gen_apr, " with autopay."],
             ["pricing"]),
        ]
    if product == "deposit_account":
        choices += [
            (["Earn ", gen_apy, " on every dollar."], ["pricing"]),
            (["Open a high-yield savings account at ", gen_apy, "."], ["pricing"]),
        ]
    if product == "investment":
        choices += [
            (["Grow your investment portfolio with ", gen_pct,
              " annual returns."], ["pricing", "performance"]),
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
        ]
    if not choices:
        choices = [(["Save ", gen_pct, " with ", product.replace("_", " "), "."],
                    ["pricing", "performance"])]
    return rng.choice(choices)


def _body_specs(rng, product):
    specs = []
    # A comparison table-ish body with an amount.
    if product in _CREDIT_LIKE:
        specs.append(("body",
                      ["Borrow up to ", gen_amount, " with a ", gen_time,
                       " term."], ["pricing"]))
    if product == "deposit_account":
        specs.append(("body",
                      ["No minimum balance and ", gen_fee, "."], ["pricing"]))
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
# Routing policy (ground truth) — the settled deterministic policy.
# ---------------------------------------------------------------------------

def _intended_routing(product, has_rate, fdic, endorsement, optout, states):
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
    return list(dict.fromkeys(fw))


# ---------------------------------------------------------------------------
# Asset assembly
# ---------------------------------------------------------------------------

_PRODUCTS = ["credit_card", "personal_loan", "mortgage", "auto_loan", "bnpl",
             "deposit_account", "investment", "crypto", "insurance",
             "credit_repair"]

_SKIP_CLAIM_ROLES = {"disclosure", "legal", "fine_print"}


def generate_asset(rng: random.Random, idx: int) -> dict:
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
    has_rate = any(e["entity_type"] in ("apr", "rate") for e in entities)
    states = [rng.choice(_STATES)] if rng.random() < 0.35 else []
    frameworks = _intended_routing(product, has_rate, fdic, endorsement,
                                   optout, states)

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
# OCR-noise augmentation (robustness split): corrupts SEGMENT TEXT only,
# leaving routing/segment-role/claim-type ground truth valid. Entity spans
# are dropped from the noised copy (their offsets no longer hold), so the
# robustness split is scored on segments/claims/routing, not exact spans.
# ---------------------------------------------------------------------------

_CONFUSE = {"o": "0", "O": "0", "l": "1", "I": "1", "S": "5", "B": "8"}


def _noise_text(rng, text, rate=0.06):
    out = []
    for ch in text:
        r = rng.random()
        if ch in _CONFUSE and r < rate:
            out.append(_CONFUSE[ch])
        elif r < rate / 3:
            continue  # dropped char
        else:
            out.append(ch)
    return "".join(out)


def augment_ocr_noise(asset: dict, rng: random.Random) -> dict:
    a = json.loads(json.dumps(asset))
    a["asset_id"] = asset["asset_id"] + "_noisy"
    for s in a["segments"]:
        s["text"] = _noise_text(rng, s["text"])
    for c in a["claim_candidates"]:
        seg = next(s for s in a["segments"] if s["segment_id"] == c["segment_id"])
        c["text"] = seg["text"]
        c["char_span"] = {"start": 0, "end": len(seg["text"])}
    a["entities"] = []  # spans invalid after corruption
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

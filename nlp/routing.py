"""Framework routing: segments + entities -> one RoutingLabel dict.

Deterministic keyword/entity rules decide which regulatory frameworks
get a look at the asset. Routing is triage, not judgment — inclusion
means "this framework's rules should run", never "this asset violates".
Over-inclusion is cheap; a missed framework is a silent review gap.

Output matches ``schema.RoutingLabel`` exactly: product_type,
frameworks (>= 1), and a human-readable ``signal`` audit trail.
"""

from __future__ import annotations

import re

# Most matches wins; earlier rule breaks ties. Comparative ads name
# competitor product categories ("...vs credit card"), so a single hit
# must not outvote the advertised product. Specific products before
# generic deposit/credit wording so "home equity line" doesn't land in
# deposit_account via a stray "account".
_PRODUCT_RULES = [
    ("mortgage", r"\bmortgage\b|\bhome equity\b|\bheloc\b|\brefinanc"),
    ("auto_loan", r"\bauto loan\b|\bcar (?:loan|financing)\b"),
    ("credit_card", r"\bcredit card\b|\bcash back\b|\bcard member\b"),
    ("personal_loan", r"\bpersonal loan\b|\bdebt consolidation\b|\bconsolidat"),
    ("bnpl", r"\bpay in \d\b|\bbuy now,? pay later\b|\bbnpl\b"),
    ("credit_repair", r"\bdebt relief\b|\bdebt settlement\b|\bcredit repair\b|"
                      r"\bfix your credit\b"),
    ("crypto", r"\bcrypto|\bbitcoin\b|\bethereum\b|\btoken\b"),
    ("investment", r"\binvest|\bportfolio\b|\betf\b|\bstocks?\b|\bbrokerage\b|"
                   r"\breturns?\b|\bsecurities\b"),
    ("insurance", r"\binsurance\b|\bcoverage\b|\bpremiums?\b|\bpolicy\b"),
    ("deposit_account", r"\bapy\b|\bsavings\b|\bchecking\b|\bdeposit\b|"
                        r"\boverdraft\b|\bfdic\b|\bbank account\b"),
]

_CREDIT_PRODUCTS = {"credit_card", "personal_loan", "mortgage", "auto_loan",
                    "bnpl", "credit_repair"}

# ------------------------------------------- semantic fallback (frozen)
# Fires ONLY when rules found nothing: no entities and zero product-rule
# hits, but the text still sounds financial. Uses the frozen embedding
# model to suggest a candidate framework; the signal is marked so
# downstream consumers can always tell fallback routing from rule routing.

_FINANCIAL_RE = re.compile(
    r"\b(?:money|cash|bank|financ|loan|lend|borrow|credit|debit|card|"
    r"pay(?:ment)?s?|rate|interest|apr|apy|account|fund|invest|wealth|"
    r"nest egg|budget|spend|debt|mortgage|insur)\w*",
    re.IGNORECASE,
)

SEMANTIC_FALLBACK_MARKER = "semantic-similarity fallback, no rule match"
SEMANTIC_ROUTE_THRESHOLD = 0.35  # tunable; routing is triage, over-inclusion is cheap

# (topic, reference marketing sentence, frameworks it suggests)
_SEMANTIC_REFERENCES = [
    ("credit/APR marketing",
     "Apply now for a credit card or loan with a low APR interest rate.",
     ["TILA", "CFPB"]),
    ("deposit/savings marketing",
     "Open a savings account and earn a high yield on your bank deposit.",
     ["Reg_DD", "CFPB"]),
    ("investment returns marketing",
     "Invest your money and grow your portfolio with strong returns.",
     ["SEC", "FINRA"]),
    ("email marketing",
     "Subscribe to our marketing emails, or unsubscribe at any time.",
     ["CAN-SPAM"]),
]


def _semantic_route(full_text: str):
    """(score, topic, frameworks) of the closest reference sentence, or
    None if nothing clears SEMANTIC_ROUTE_THRESHOLD."""
    from nlp.embeddings import semantic_similarity

    best = None
    for topic, reference, frameworks in _SEMANTIC_REFERENCES:
        score = semantic_similarity(full_text, reference)
        if best is None or score > best[0]:
            best = (score, topic, frameworks)
    return best if best[0] >= SEMANTIC_ROUTE_THRESHOLD else None


def _get(obj, key):
    return obj[key] if isinstance(obj, dict) else getattr(obj, key)


def route(segments: list, entities: list) -> dict:
    """One schema.RoutingLabel-shaped dict for the asset."""
    full_text = " ".join(_get(s, "text") for s in segments)
    entity_types = {str(_get(e, "entity_type")) for e in entities}

    product_type = "unknown"
    best_hits = 0
    for product, pattern in _PRODUCT_RULES:
        hits = len(re.findall(pattern, full_text, re.IGNORECASE))
        if hits > best_hits:
            product_type, best_hits = product, hits

    # Rules found nothing at all -> try the frozen-embedding fallback on
    # financial-sounding text. Rule-based routing below stays untouched
    # whenever entities or product wording matched.
    if not entities and best_hits == 0 and _FINANCIAL_RE.search(full_text):
        hit = _semantic_route(full_text)
        if hit is not None:
            score, topic, suggested = hit
            return {
                "product_type": "unknown",
                "frameworks": list(dict.fromkeys(["FTC"] + suggested)),
                "signal": (
                    f"{SEMANTIC_FALLBACK_MARKER}: closest reference "
                    f"'{topic}' (cosine {score:.2f}) -> "
                    + " + ".join(suggested)
                ),
            }

    frameworks = ["FTC"]  # marketing claims are FTC's baseline remit
    reasons = ["marketing asset -> FTC"]

    has_rate = bool(entity_types & {"apr", "rate"})
    if product_type == "deposit_account":
        frameworks.append("Reg_DD")
        reasons.append("deposit product"
                       + (" with rate/APY" if has_rate else "")
                       + " -> Reg DD")
        frameworks.append("CFPB")
        reasons.append("consumer financial product -> CFPB UDAAP")
    elif has_rate or product_type in _CREDIT_PRODUCTS:
        why = []
        if has_rate:
            why.append("APR/rate entity")
        if product_type in _CREDIT_PRODUCTS:
            why.append(f"credit product ({product_type})")
        frameworks += ["TILA", "CFPB"]
        reasons.append(" + ".join(why) + " -> TILA advertising rules + CFPB")

    if product_type in ("investment", "crypto"):
        frameworks += ["SEC", "FINRA"]
        reasons.append(f"{product_type} product / return claims -> SEC + FINRA")

    if "endorsement_marker" in entity_types:
        reasons.append("endorsement marker -> FTC endorsement guides (16 CFR 255)")

    if "optout_marker" in entity_types:
        frameworks += ["CAN-SPAM", "TCPA"]
        reasons.append("opt-out language -> CAN-SPAM / TCPA")

    # dedupe, keep first-mention order
    frameworks = list(dict.fromkeys(frameworks))
    return {
        "product_type": product_type,
        "frameworks": frameworks,
        "signal": "; ".join(reasons),
    }


if __name__ == "__main__":
    import glob
    import json
    import os
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    import schema
    from nlp.entities import extract_entities

    for path in sorted(glob.glob(os.path.join(root, "data/gold/*.json")))[:3]:
        gold = json.load(open(path))
        segments = gold["segments"]
        r = route(segments, extract_entities(segments))
        schema.RoutingLabel.model_validate(r)
        src = ("SEMANTIC-FALLBACK" if SEMANTIC_FALLBACK_MARKER in r["signal"]
               else "RULES")
        print(f"[{src}] {gold['asset_id']}: {r['product_type']} "
              f"{r['frameworks']}\n         signal: {r['signal']}\n")

    # Synthetic asset: financial wording, but zero entities and zero
    # product-rule hits — the case the semantic fallback exists for.
    demo = [{"segment_id": "seg_1", "role": "headline", "source": "text",
             "text": "Put your money to work and watch your nest egg grow"}]
    r = route(demo, [])
    schema.RoutingLabel.model_validate(r)
    src = ("SEMANTIC-FALLBACK" if SEMANTIC_FALLBACK_MARKER in r["signal"]
           else "RULES")
    print(f"[{src}] synthetic-no-rule-match: {r['product_type']} "
          f"{r['frameworks']}\n         signal: {r['signal']}")

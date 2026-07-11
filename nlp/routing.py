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
    # Bare "refinanc" is intentionally absent: "refinance your car" is an
    # auto loan, so refinancing only routes mortgage with home context.
    ("mortgage", r"\bmortgage\b|\bhome equity\b|\bheloc\b|"
                 r"\bhome loan\b|\bhome financing\b|"
                 r"\brefinance? your (?:home|house|mortgage)\b|"
                 r"\bmortgage refinanc|\brefinance? your rate\b"),
    ("auto_loan", r"\bauto (?:loan|financing|refinance)\b|"
                  r"\bcar (?:loan|financing|refinance)\b|"
                  r"\bvehicle (?:loan|financing)\b|"
                  r"\brefinance your (?:car|auto|vehicle)\b"),
    ("credit_card", r"\bcredit card\b|\bcash back\b|\bcard member\b|"
                    r"\brewards card\b|\bcash[- ]back card\b|"
                    r"\bbalance transfer\b|\b0% intro apr\b|\bintro apr\b"),
    ("personal_loan", r"\bpersonal loan\b|\bdebt consolidation\b|\bconsolidat"),
    ("bnpl", r"\bpay in \d\b|\bbuy now,? pay later\b|\bbnpl\b|"
             r"\binterest[- ]free (?:payments|installments)\b|"
             r"\bsplit your (?:purchase|payment)\b|\b4 (?:easy )?payments\b"),
    ("credit_repair", r"\bdebt relief\b|\bdebt settlement\b|\bcredit repair\b|"
                      r"\bfix your credit\b"),
    ("crypto", r"\bcrypto|\bbitcoin\b|\bethereum\b|\btoken\b|\bweb3\b|"
               r"\bstablecoin\b|\bdigital asset\b|\bdefi\b|\bstaking\b"),
    # "returns" only in an investment sense — bare \breturns?\b matched
    # "free returns" on retail ads.
    ("investment", r"\binvest|\bportfolio\b|\betf\b|\bstocks?\b|\bbrokerage\b|"
                   r"\b(?:annual|market|strong|high|investment)\s+returns?\b|"
                   r"\breturns? on (?:investment|your money)\b|\bsecurities\b"),
    # "policy" only in an insurance sense — bare \bpolicy\b matched
    # "privacy policy" boilerplate.
    ("insurance", r"\binsurance\b|\bcoverage\b|\bpremiums?\b|"
                  r"\b(?:insurance|life|auto|home|health)\s+polic(?:y|ies)\b|"
                  r"\bpolicyholders?\b"),
    # Deposit-ADVERTISING terms only. FDIC-insured-status wording is
    # deliberately absent: "Member FDIC" says who insures the advertiser,
    # not what product the ad sells (docs/check_taxonomy.md change
    # request #2) — it routes the FDIC framework below instead. The
    # lookahead keeps "deposit insurance" (insured-status phrasing) from
    # counting as a deposit-terms hit.
    # Bare "savings" is cost-savings marketing ("72% savings on
    # interest"), not a deposit product — require account context.
    ("deposit_account", r"\bapy\b|\bsavings account\b|"
                        r"\bhigh[- ]yield savings\b|\bchecking\b|"
                        r"\bdeposit(?!\s+insurance)\b|"
                        r"\boverdraft\b|\bbank account\b|"
                        r"\bmoney market\b|\bcertificate of deposit\b|\bcd account\b"),
]

_CREDIT_PRODUCTS = {"credit_card", "personal_loan", "mortgage", "auto_loan",
                    "bnpl", "credit_repair"}

# TILA advertising rules (Reg Z, 12 CFR 1026.24) and ECOA/Reg B (12 CFR
# 1002) both govern *extensions of consumer credit*. credit_repair /
# debt relief is a service, not an extension of credit, so it draws
# neither — only CFPB UDAAP. (Same rationale for both sets; kept
# separate for clarity should the taxonomy diverge later.)
_ECOA_PRODUCTS = {"credit_card", "personal_loan", "mortgage", "auto_loan",
                  "bnpl"}
_TILA_PRODUCTS = _ECOA_PRODUCTS

# Insured-status wording -> FDIC Part 328 framework. Independent of
# product routing by design: who-insures wording appears on brand ads,
# hybrid ads, and misrepresentations alike.
_FDIC_RE = re.compile(
    r"\bmember\s+fdic\b|\bfdic[- ]insured\b|\bfdic\b|\bncua\b|"
    r"\bfederally\s+insured\b|\bdeposit\s+insurance\b|"
    r"\bpass[- ]through\s+insurance\b",
    re.IGNORECASE,
)

_STATE_CODE_RE = re.compile(r"US-[A-Z]{2}")

# Product classification is role-weighted, not a flat full-text count:
# the advertised product lives in the headline/body, while disclosures
# and legal boilerplate ("...average APR of 25.33%...", "Member FDIC",
# long fine print naming other products) must not outvote it. Weights
# scale each segment's keyword hits by how load-bearing its role is.
_ROLE_WEIGHT = {
    "headline": 2.0, "cta": 1.5, "body": 1.0, "unknown": 1.0,
    "disclosure": 0.25, "fine_print": 0.25, "legal": 0.1,
}


def _role(seg) -> str:
    r = seg.get("role", "unknown") if isinstance(seg, dict) else getattr(seg, "role", "unknown")
    return str(getattr(r, "value", r) or "unknown")

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
    None if nothing clears SEMANTIC_ROUTE_THRESHOLD.

    Returns None (never raises) when the embedding backend is
    unavailable, so an offline/cold-cache run degrades to rules-only
    routing instead of crashing the whole pipeline. Input is capped to
    MAX_INPUT_CHARS because MiniLM truncates long text to an arbitrary
    prefix.
    """
    try:
        from nlp.embeddings import MAX_INPUT_CHARS, semantic_similarity
    except Exception:  # noqa: BLE001
        return None

    text = full_text[:MAX_INPUT_CHARS]
    best = None
    try:
        for topic, reference, frameworks in _SEMANTIC_REFERENCES:
            score = semantic_similarity(text, reference)
            if best is None or score > best[0]:
                best = (score, topic, frameworks)
    except Exception:  # noqa: BLE001 — missing model must not crash routing
        return None
    return best if best[0] >= SEMANTIC_ROUTE_THRESHOLD else None


def _get(obj, key):
    return obj[key] if isinstance(obj, dict) else getattr(obj, key)


def _state_targets(target_jurisdictions) -> list[str]:
    """US state codes among the user-supplied targeting, in given order."""
    return [c for c in (target_jurisdictions or [])
            if _STATE_CODE_RE.fullmatch(c)]


def route(segments: list, entities: list,
          target_jurisdictions: list[str] | None = None) -> dict:
    """One schema.RoutingLabel-shaped dict for the asset.

    ``target_jurisdictions`` is the user-supplied ad-targeting list from
    scan time ("US" or "US-XX"); any state code additionally routes the
    STATE_UDAP umbrella framework.
    """
    full_text = " ".join(_get(s, "text") for s in segments)
    entity_types = {str(_get(e, "entity_type")) for e in entities}
    states = _state_targets(target_jurisdictions)
    # Wording-keyed, not product-keyed: applies on every routing path,
    # including the semantic fallback below.
    fdic_wording = bool(_FDIC_RE.search(full_text))

    product_type = "unknown"
    best_score = 0.0
    for product, pattern in _PRODUCT_RULES:
        rx = re.compile(pattern, re.IGNORECASE)
        score = sum(len(rx.findall(_get(s, "text"))) * _ROLE_WEIGHT.get(_role(s), 1.0)
                    for s in segments)
        if score > best_score:  # ties keep the earlier (more specific) rule
            product_type, best_score = product, score

    # Rules found nothing at all -> try the frozen-embedding fallback on
    # financial-sounding text. Rule-based routing below stays untouched
    # whenever entities or product wording matched.
    if not entities and best_score == 0.0 and _FINANCIAL_RE.search(full_text):
        hit = _semantic_route(full_text)
        if hit is not None:
            score, topic, suggested = hit
            frameworks = list(dict.fromkeys(["FTC"] + suggested))
            signal = (f"{SEMANTIC_FALLBACK_MARKER}: closest reference "
                      f"'{topic}' (cosine {score:.2f}) -> "
                      + " + ".join(suggested))
            if fdic_wording:
                frameworks.append("FDIC")
                signal += "; insured-status wording -> FDIC Part 328"
            if states:
                frameworks.append("STATE_UDAP")
                signal += (f"; targets {', '.join(states)} -> "
                           f"state UDAP applies")
            return {
                "product_type": "unknown",
                "frameworks": frameworks,
                "signal": signal,
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
    elif has_rate or product_type in _TILA_PRODUCTS:
        why = []
        if has_rate:
            why.append("APR/rate entity")
        if product_type in _TILA_PRODUCTS:
            why.append(f"credit product ({product_type})")
        frameworks += ["TILA", "CFPB"]
        reasons.append(" + ".join(why) + " -> TILA advertising rules + CFPB")
    elif product_type in _CREDIT_PRODUCTS:
        # credit-related service that isn't an extension of credit
        # (credit_repair / debt relief): CFPB UDAAP, but no TILA/ECOA.
        frameworks.append("CFPB")
        reasons.append(f"credit-related service ({product_type}) -> CFPB UDAAP")

    if product_type in _ECOA_PRODUCTS:
        frameworks.append("ECOA")
        reasons.append(f"credit product ({product_type}) -> ECOA/Reg B")

    if fdic_wording:
        frameworks.append("FDIC")
        reasons.append("insured-status wording -> FDIC Part 328")

    if product_type in ("investment", "crypto"):
        frameworks += ["SEC", "FINRA"]
        reasons.append(f"{product_type} product / return claims -> SEC + FINRA")

    if "endorsement_marker" in entity_types:
        reasons.append("endorsement marker -> FTC endorsement guides (16 CFR 255)")

    if "optout_marker" in entity_types:
        frameworks += ["CAN-SPAM", "TCPA"]
        reasons.append("opt-out language -> CAN-SPAM / TCPA")

    if states:
        frameworks.append("STATE_UDAP")
        reasons.append(f"targets {', '.join(states)} -> state UDAP applies")

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

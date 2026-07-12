"""Versioned routing lexicons for the coverage-matrix framework triggers.

Compiled wording triggers for ``nlp.routing`` — the routing_trigger
column of docs/coverage_matrix.md, interpreted once at authoring time
into constants. Editing any table here is a version bump
(ROUTING_LEXICON_VERSION), and the whole module is hashed into the
root ``version.ruleset_hash`` alongside the entity patterns and product
rules, so stale evals are detectable.

Matching mirrors rule_engine.lexicons: longest-first, word-bounded,
case-insensitive. Routing is triage — over-inclusion is cheap, a missed
framework is a silent review gap — so lexemes lean inclusive, but avoid
known ambiguities (e.g. bare "discover" would match "Discover the
difference"; only "discover card"/"discover it" are card-network hits).
"""

from __future__ import annotations

import re

ROUTING_LEXICON_VERSION = "v1"

#: Wording triggers, keyed by trigger name. See _LEXICON_ROUTES in
#: nlp.routing for the framework(s) each one routes.
ROUTING_LEXICONS: dict[str, tuple[str, ...]] = {
    # MLA (32 CFR 232) + SCRA: military/servicemember-targeted credit.
    "MILITARY": ("servicemember", "servicemembers", "service member",
                 "service members", "military", "active duty",
                 "active-duty", "armed forces", "veteran", "veterans",
                 "va loan", "mapr", "military annual percentage rate",
                 "military lending act"),
    # FDCPA / Reg F: debt-collection messaging. Deliberately excludes
    # "debt relief"/"debt consolidation" (credit_repair product wording).
    "DEBT_COLLECTION": ("debt collector", "debt collection",
                        "collect a debt", "attempt to collect",
                        "collection agency", "past-due balance",
                        "delinquent account", "charged-off"),
    # FCRA / Reg V: prescreened / firm-offer-of-credit wording.
    "PRESCREEN": ("pre-approved", "preapproved", "prescreened",
                  "pre-screened", "pre-selected", "preselected",
                  "firm offer of credit", "you have been selected"),
    # Reg E / EFTA: P2P, prepaid, and transfer services.
    "EFT_P2P": ("send money", "money transfer", "transfer money", "p2p",
                "peer-to-peer", "prepaid card", "prepaid debit",
                "remittance", "mobile wallet", "digital wallet",
                "instant transfer"),
    # CFTC/NFA: futures / forex / commodities promotion.
    "CFTC_TRADING": ("futures", "forex", "foreign exchange",
                     "commodity trading", "commodities trading", "cfd",
                     "cfds", "margin trading"),
    # COPPA: under-13-directed creative signals (coverage mechanization).
    "CHILD_DIRECTED": ("for kids", "kids app", "kids account", "under 13",
                       "under age 13", "parental consent", "kid-friendly",
                       "children under"),
    # CAN-SPAM: email-structured creative.
    "EMAIL_STRUCTURE": ("unsubscribe", "view in browser",
                        "email preferences", "you received this email",
                        "manage subscriptions",
                        "stop receiving these emails"),
    # TCPA: SMS / call-to-text / phone-consent language.
    "SMS_CONSENT": ("reply stop", "text stop", "msg & data rates",
                    "msg and data rates", "message and data rates",
                    "consent to receive calls", "consent to receive texts",
                    "consent to be contacted", "automated calls",
                    "autodialed", "call or text"),
    # GLBA (Reg P) + STATE_PRIVACY: privacy-policy / data-use claims.
    "PRIVACY_DATA": ("privacy policy", "personal information", "your data",
                     "data sharing", "information we collect",
                     "do not sell", "opt out of sharing",
                     "sell your information", "share your information"),
    # SEC Marketing Rule + FINRA 2210: adviser / broker-dealer wording.
    "SECURITIES_PRO": ("registered investment adviser",
                       "investment adviser", "investment advisor",
                       "broker-dealer", "broker dealer",
                       "advisory services", "wealth management", "ria"),
    # Securities Act ad rules (482 / 34b-1): fund advertising.
    "FUND_AD": ("mutual fund", "mutual funds", "index fund", "index funds",
                "etf", "etfs", "prospectus", "expense ratio",
                "money market fund", "target-date fund"),
    # Card network standards: network names/marks in creative text.
    "CARD_NETWORKS": ("visa", "mastercard", "american express", "amex",
                      "discover card", "discover it"),
    # NMLS licensing disclosure (SAFE Act): NMLS ID presence.
    "NMLS_ID": ("nmls",),
}

#: Card-network names looked up in semantic_signals values (logo/label
#: detections from the paid OCR tier).
CARD_NETWORK_SIGNALS = ("visa", "mastercard", "american express", "amex",
                        "discover")

#: States with FTSA-type mini-TCPA telemarketing statutes (v1 list;
#: FL FTSA is the archetype). Routed as the MINI_TCPA umbrella when the
#: asset both triggers TCPA and targets one of these jurisdictions.
MINI_TCPA_STATES = frozenset({
    "US-FL", "US-OK", "US-WA", "US-AZ", "US-CT", "US-MD", "US-NJ",
    "US-GA", "US-TX", "US-VA",
})

_COMPILED: dict[str, re.Pattern] = {}


def _pattern(name: str) -> re.Pattern:
    if name not in _COMPILED:
        parts = []
        # Longest-first so multi-word members win over their prefixes.
        for member in sorted(ROUTING_LEXICONS[name], key=len, reverse=True):
            lead = r"\b" if member[0].isalnum() else ""
            tail = r"\b" if member[-1].isalnum() else ""
            parts.append(lead + re.escape(member) + tail)
        _COMPILED[name] = re.compile("|".join(parts), re.IGNORECASE)
    return _COMPILED[name]


def match_routing(name: str, text: str) -> list[str]:
    """Matched lexemes (lowercased, deduped, in match order) in text."""
    seen: dict[str, None] = {}
    for m in _pattern(name).findall(" ".join(text.split())):
        seen.setdefault(m.lower())
    return list(seen)

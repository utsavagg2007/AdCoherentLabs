"""Version identity for pipeline output provenance.

``ruleset_hash`` is derived from the actual extraction rules (spaCy
Matcher/EntityRuler patterns plus the claim/routing regexes), so any
pattern edit changes the hash and stale evals are detectable without
manual version bumps.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

CV_VERSION = "cv-0.1.0"
NLP_VERSION = "nlp-0.1.0"


def ruleset_hash() -> str:
    """Stable hash of every deterministic extraction rule."""
    from nlp import claims, entities, routing, routing_lexicon

    payload = json.dumps(
        {
            "matcher": entities._MATCHER_PATTERNS,
            "ruler": entities._RULER_PATTERNS,
            "priority": entities._PRIORITY,
            "claims_kw": {k: v.pattern for k, v in
                          claims._KEYWORD_CLAIMS.items()},
            "claims_ent": claims._ENTITY_CLAIMS,
            "claims_sem": [claims._SEMANTIC_REFERENCES,
                           claims.SEMANTIC_CLAIM_THRESHOLD],
            "routing": routing._PRODUCT_RULES,
            "routing_sem": [routing._SEMANTIC_REFERENCES,
                            routing.SEMANTIC_ROUTE_THRESHOLD],
            "routing_lex": [routing_lexicon.ROUTING_LEXICON_VERSION,
                            routing_lexicon.ROUTING_LEXICONS,
                            sorted(routing_lexicon.MINI_TCPA_STATES),
                            routing_lexicon.CARD_NETWORK_SIGNALS,
                            routing._LEXICON_ROUTES],
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def make_provenance(embedding_model_version: str | None = None,
                    ocr_backend: str | None = None) -> dict:
    """schema.Provenance-shaped dict stamped with the current time.

    Pass the exact embedding model name+revision whenever a semantic
    (embedding-based) fallback contributed to the output; leave None for
    purely rule-based runs. Pass the OCR backend name ('paddle',
    'tesseract', 'google_vision') for image-sourced assets — backends
    have different measured accuracy floors (cv.ocr.MEASURED_FLOORS),
    so every representation must name the engine that transcribed it.
    """
    return {
        "cv_version": CV_VERSION,
        "nlp_version": NLP_VERSION,
        "ruleset_hash": ruleset_hash(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "embedding_model_version": embedding_model_version,
        "ocr_backend": ocr_backend,
    }

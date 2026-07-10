"""Ruleset identity: version constant + content hash for audit trails.

Every EngineReport is stamped with RULESET_VERSION and ruleset_hash().
The hash covers each registered check's id, registration metadata
(families, frameworks, scope), and its exact source code, plus the
lexicon and threshold tables — so two reports with equal hashes were
produced by byte-identical rules, and any edit to a check, lexicon, or
threshold changes the hash even if someone forgets to bump the version.

Distinct from the repo-root version.py: that stamps the CV/NLP layers'
provenance (schema.Provenance.ruleset_hash); this one identifies the
rule engine.

Determinism guard (see rule_engine/core.py): stdlib only.
"""

from __future__ import annotations

import hashlib
import inspect
import json

#: Bump on any semantic change to checks, lexicons, or thresholds.
#: History: 1.0.0 taxonomy v1 (45 checks); 1.1.0 review/asset scope split.
RULESET_VERSION = "1.1.0"

_cache: dict[tuple, str] = {}


def _source_of(fn) -> str:
    """Exact source when available; deterministic bytecode fingerprint
    otherwise (REPL/exec-registered checks must not crash the hash —
    a crashing guardrail is worse than a coarser fingerprint)."""
    try:
        return inspect.getsource(fn)
    except OSError:
        return (f"<no-source> {fn.__module__}.{fn.__qualname__} "
                f"bytecode:{fn.__code__.co_code.hex()}")


def ruleset_hash(registry: dict | None = None) -> str:
    """sha256 (16 hex chars) over the full ruleset content.

    ``registry`` defaults to rule_engine.core.CHECK_REGISTRY; the runner
    passes its own so the hash always describes the registry that
    actually ran.
    """
    if registry is None:
        from rule_engine.core import CHECK_REGISTRY
        registry = CHECK_REGISTRY
    key = tuple(sorted(registry))
    if key not in _cache:
        from rule_engine import checks_universal, lexicons

        payload = {
            "ruleset_version": RULESET_VERSION,
            "checks": {
                cid: {"families": list(c.families),
                      "frameworks": list(c.frameworks),
                      "scope": c.scope,
                      "source": _source_of(c.fn)}
                for cid, c in sorted(registry.items())
            },
            "lexicons": {"version": lexicons.LEXICON_VERSION,
                         "table": lexicons.LEXICONS},
            "thresholds": {"version": lexicons.THRESHOLDS_VERSION,
                           "PROX_MAX": lexicons.PROX_MAX,
                           "HEIGHT_MIN_PCT": lexicons.HEIGHT_MIN_PCT,
                           "APR_HEIGHT_RATIO_MIN": lexicons.APR_HEIGHT_RATIO_MIN,
                           "NUM_TOL": checks_universal.NUM_TOL},
        }
        blob = json.dumps(payload, sort_keys=True).encode()
        _cache[key] = hashlib.sha256(blob).hexdigest()[:16]
    return _cache[key]

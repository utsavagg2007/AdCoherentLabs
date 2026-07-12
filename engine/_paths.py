"""sys.path bootstrap: make both layer repos importable in one process.

The four layers live in two sibling repos:

    CV-RULE_ENG-NLP/   flat modules: pipeline, schema, llm_contract,
                       config, version + packages cv/, nlp/, rule_engine/
    rag-engine/        package: adcoherent_rag (retrieval + LLM review)

Import THIS module before importing anything from either repo. CV root
is inserted first so its flat top-level modules (``schema``, ``config``,
``pipeline``, ``version``) always win name resolution; rag-engine only
contributes the ``adcoherent_rag`` package, so there is no collision.

A root-level ``.env`` (next to this package) is loaded first, without
overriding variables already set in the environment — one place to
configure the whole engine (both repos also load their own .env files;
those remain effective for anything the root file does not set).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CV_ROOT = PROJECT_ROOT / "CV-RULE_ENG-NLP"
RAG_ROOT = PROJECT_ROOT / "rag-engine"

_missing = [p for p in (CV_ROOT, RAG_ROOT) if not p.is_dir()]
if _missing:
    raise ImportError(
        "engine package expects the layer repos next to it; missing: "
        + ", ".join(str(p) for p in _missing)
    )

# Root .env first (no override), before either repo's config module runs.
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:  # pragma: no cover - dotenv ships with both repos
    pass

for _root in (RAG_ROOT, CV_ROOT):  # insert CV last so it ends up first
    _s = str(_root)
    if _s in sys.path:
        sys.path.remove(_s)
    sys.path.insert(0, _s)

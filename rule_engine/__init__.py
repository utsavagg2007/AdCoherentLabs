"""Deterministic compliance guardrail engine.

Pure Python, zero model calls, zero network calls at check time. Consumes
schema.AssetRepresentation + llm_contract.LLMOutput and reports pass or a
structured failure list. Check definitions live in docs/check_taxonomy.md;
the registry/runner machinery is rule_engine.core.
"""

from rule_engine.core import (
    CHECK_REGISTRY,
    FAMILIES,
    CheckContext,
    CheckResult,
    EngineReport,
    register_check,
    run_checks,
)
from rule_engine.version import RULESET_VERSION, ruleset_hash

# Importing check modules populates CHECK_REGISTRY as a side effect, so
# `import rule_engine` yields a ready-to-run engine.
from rule_engine import checks_universal  # noqa: E402,F401
from rule_engine import checks_ftc5  # noqa: E402,F401
from rule_engine import checks_regz  # noqa: E402,F401
from rule_engine import checks_regdd  # noqa: E402,F401
from rule_engine import checks_fdic328  # noqa: E402,F401
from rule_engine import checks_regb  # noqa: E402,F401

__all__ = [
    "CHECK_REGISTRY",
    "FAMILIES",
    "RULESET_VERSION",
    "CheckContext",
    "CheckResult",
    "EngineReport",
    "register_check",
    "ruleset_hash",
    "run_checks",
]

"""Determinism audit: AST scan of every rule_engine module.

Enforces the invariant declared in rule_engine/core.py: check modules
must stay pure Python — standard library plus the two pydantic contract
modules (schema, llm_contract) only. Zero model calls, zero network
calls, zero nondeterministic inputs at check time. Any import of a
third-party package (requests, numpy, torch, spacy, ...) from a
rule_engine module fails the audit.

The scan is static (ast.parse — nothing is imported or executed), so it
is safe to run anywhere and cannot be fooled by import-time side
effects it would itself trigger.

Usage (CI gate):
    python -m rule_engine.determinism_audit    # exit 0 clean, 1 dirty
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

#: Non-stdlib roots a rule_engine module may import.
ALLOWED_ROOTS = frozenset({"schema", "llm_contract", "pydantic",
                           "rule_engine"})


def _is_stdlib(root: str) -> bool:
    if root in getattr(sys, "stdlib_module_names", ()):  # 3.10+
        return True
    try:
        spec = importlib.util.find_spec(root)
    except (ImportError, ValueError):
        return False
    if spec is None:
        return False
    origin = spec.origin or ""
    return (origin in ("built-in", "frozen")
            or ("lib/python" in origin and "site-packages" not in origin))


def audit(package_dir: Path | None = None) -> list[tuple[str, str]]:
    """Return [(module, offending_import)] — empty when clean."""
    package_dir = package_dir or Path(__file__).resolve().parent
    violations: list[tuple[str, str]] = []
    for py in sorted(package_dir.glob("*.py")):
        tree = ast.parse(py.read_text(), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                # Relative imports resolve inside the package: allowed.
                names = [] if node.level else [node.module]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                if root in ALLOWED_ROOTS or _is_stdlib(root):
                    continue
                violations.append((py.name, name))
    return violations


def main() -> int:
    violations = audit()
    scanned = len(list(Path(__file__).resolve().parent.glob("*.py")))
    if violations:
        print(f"DETERMINISM AUDIT FAILED — {len(violations)} forbidden "
              f"import(s) in rule_engine/:")
        for module, name in violations:
            print(f"  {module}: import {name}")
        return 1
    print(f"determinism audit clean: {scanned} rule_engine modules, "
          "stdlib + contracts only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

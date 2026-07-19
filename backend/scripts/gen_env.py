"""Deprecated alias — the backend no longer has its own env file.

The whole backend + engine now read the single repo-root ``.env``. Use:

    python scripts/sync_env.py

This shim regenerates just the root ``.env`` (``--only root``) and stays for
muscle-memory / older docs. Prints fingerprints only — never secret values.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from sync_env import DEFAULT_STACK, run  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK)
    ap.add_argument("--allow-defaults", action="store_true")
    args = ap.parse_args()
    print("note: backend/scripts/gen_env.py is deprecated - use scripts/sync_env.py")
    return run(args.stack_dir, only={"root"}, allow_defaults=args.allow_defaults)


if __name__ == "__main__":
    sys.exit(main())

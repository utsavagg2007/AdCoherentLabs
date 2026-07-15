"""Write backend/.env from the (rotated) Supabase stack .env — spec P0.

    python backend/scripts/gen_env.py [--stack-dir C:\\Users\\HP\\supabase-project]
                                      [--allow-defaults]

This is now a thin shim over ``scripts/sync_env.py --only backend`` — the single
implementation that also regenerates the root and rag-engine env files and,
critically, probes the database for the password it ACTUALLY accepts (a
half-applied rotation is detected instead of silently breaking DB access).
Prefer ``python scripts/sync_env.py`` to regenerate every env file at once.

Prints fingerprints only — never secret values.
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
    return run(args.stack_dir, only={"backend"}, allow_defaults=args.allow_defaults)


if __name__ == "__main__":
    sys.exit(main())

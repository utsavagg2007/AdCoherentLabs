"""RED-LINE wrapper: the credit race test (supabase/tests/credit_race_test.py)
as a pytest gate — a failure blocks merge (§16)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.needs_db, pytest.mark.redline]

REPO = Path(__file__).resolve().parents[2]


def test_credit_race_50_parallel(stack):
    out = subprocess.run(
        [sys.executable, str(REPO / "supabase" / "tests" / "credit_race_test.py")],
        capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, f"stdout:\n{out.stdout}\nstderr:\n{out.stderr}"
    assert "CREDIT RACE TEST: PASS" in out.stdout


def test_rls_isolation_still_passes(stack):
    """The other red line: cross-tenant isolation (runs the SQL test through
    the same connection the backend uses)."""
    import psycopg

    sql = (REPO / "supabase" / "tests" / "rls_isolation_test.sql").read_text(
        encoding="utf-8")
    notices: list[str] = []
    with psycopg.connect(stack) as conn:
        conn.add_notice_handler(lambda d: notices.append(d.message_primary or ""))
        conn.execute(sql)
    assert any("RLS ISOLATION TEST: PASS" in n for n in notices), notices[-3:]

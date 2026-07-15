"""RED-LINE credit race test (Backend Architecture spec §16).

50 parallel submissions against a balance funding exactly 10 runs:
exactly 10 must succeed, the balance must never go negative, and the
ledger must sum to the stored balance afterwards. A failure here means
app.consume_credits' SELECT ... FOR UPDATE serialisation is broken and
money can leak — it blocks merge.

Run (from the repo root, any Python with psycopg):

    CV-RULE_ENG-NLP\\.venv\\Scripts\\python supabase\\tests\\credit_race_test.py

Connection comes from SUPABASE_DB_URL / DATABASE_URL (root .env is
loaded), defaulting to the local socat proxy. The throwaway tenant is
deleted afterwards; audit rows remain by design.
"""

from __future__ import annotations

import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

REPO_ROOT = Path(__file__).resolve().parents[2]
try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
except ImportError:
    pass

DB_URL = (
    os.environ.get("SUPABASE_DB_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:your-super-secret-and-long-postgres-password@127.0.0.1:54322/postgres"
)

PARALLEL = 50
FUNDED = 10
COST = 1


def provision(conn: psycopg.Connection, tag: str) -> dict:
    ids: dict = {}
    with conn.cursor() as cur:
        cur.execute(
            "insert into auth.users (instance_id, id, aud, role, email, "
            "  email_confirmed_at, created_at, updated_at) "
            "values ('00000000-0000-0000-0000-000000000000', gen_random_uuid(), "
            "  'authenticated', 'authenticated', %s, now(), now(), now()) "
            "returning id::text",
            (f"race-{tag}@test.local",),
        )
        ids["user"] = cur.fetchone()["id"]
        cur.execute(
            "insert into public.orgs (name) values (%s) returning id::text",
            (f"credit-race-{tag}",),
        )
        ids["org"] = cur.fetchone()["id"]
        # Fund the subscription bucket with EXACTLY the test balance.
        cur.execute(
            "select app.adjust_credits_manual(%s, %s, 'subscription', %s, 'race test fund')",
            (ids["org"], FUNDED * COST, ids["user"]),
        )
        # 50 pre-created runs to charge against (FK target for the ledger).
        cur.execute(
            "insert into public.submissions (org_id, created_by, title) "
            "values (%s, %s, 'race') returning id::text",
            (ids["org"], ids["user"]),
        )
        sub = cur.fetchone()["id"]
        ids["runs"] = []
        for _ in range(PARALLEL):
            cur.execute(
                "insert into public.analysis_runs (submission_id, org_id, status) "
                "values (%s, %s, 'queued') returning id::text",
                (sub, ids["org"]),
            )
            ids["runs"].append(cur.fetchone()["id"])
    conn.commit()
    return ids


def consume_one(org: str, run: str) -> bool:
    """One isolated connection = one racing submission."""
    with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select app.consume_credits(%s, %s, %s) as d", (org, run, COST)
            )
            decision = cur.fetchone()["d"]
        conn.commit()
        return bool(decision.get("allowed"))


def cleanup(ids: dict) -> None:
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            if "org" in ids:
                cur.execute("delete from public.orgs where id = %s", (ids["org"],))
            if "user" in ids:
                cur.execute("delete from auth.users where id = %s", (ids["user"],))


def main() -> int:
    tag = uuid.uuid4().hex[:8]
    failures: list[str] = []
    conn = psycopg.connect(DB_URL, row_factory=dict_row)
    ids: dict = {}
    try:
        ids = provision(conn, tag)
        print(f"provisioned org {ids['org']} funded with {FUNDED * COST} credits; "
              f"racing {PARALLEL} submissions of cost {COST}...")

        with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
            results = list(pool.map(
                lambda run: consume_one(ids["org"], run), ids["runs"]))

        allowed = sum(results)
        if allowed != FUNDED:
            failures.append(f"exactly {FUNDED} must succeed, got {allowed}")

        with conn.cursor() as cur:
            cur.execute(
                "select subscription_credits, purchased_credits "
                "from public.credit_balances where org_id = %s", (ids["org"],))
            bal = cur.fetchone()
            if bal["subscription_credits"] != 0 or bal["purchased_credits"] != 0:
                failures.append(f"balance must end at zero, got {bal}")
            if bal["subscription_credits"] < 0 or bal["purchased_credits"] < 0:
                failures.append(f"balance went NEGATIVE: {bal}")

            cur.execute(
                "select count(*) as n from app.reconcile_credit_balances() "
                "where org_id = %s", (ids["org"],))
            drift = cur.fetchone()["n"]
            if drift:
                failures.append(f"ledger does not sum to balance ({drift} bucket(s) drifted)")

            cur.execute(
                "select count(*) as n from public.credit_ledger "
                "where org_id = %s and reason = 'consume.run'", (ids["org"],))
            consumed_rows = cur.fetchone()["n"]
            if consumed_rows != FUNDED:
                failures.append(
                    f"expected {FUNDED} consume.run ledger rows, got {consumed_rows}")

        print(f"allowed={allowed}/{PARALLEL}  final balance={bal}  "
              f"consume rows={consumed_rows}  drift rows={drift}")
    finally:
        conn.close()
        try:
            cleanup(ids)
        except Exception as exc:  # noqa: BLE001
            print(f"cleanup failed for tag {tag}: {exc}", file=sys.stderr)

    if failures:
        print("CREDIT RACE TEST: FAIL")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("CREDIT RACE TEST: PASS "
          f"(exactly {FUNDED} of {PARALLEL} parallel submissions charged; "
          "balance floor held; ledger sums to balance)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

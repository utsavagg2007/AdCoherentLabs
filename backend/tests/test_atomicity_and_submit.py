"""P5 gate: charge+enqueue atomicity proven by fault injection between the
statements — they must roll back together (D3). Plus the 202/402 submission
contract and Idempotency-Key replay (§6.2)."""

from __future__ import annotations

import uuid

import pytest

from app import db as adb
from app.services import queue

from .conftest import auth, mint_jwt, q_all, q_one

pytestmark = pytest.mark.needs_db

TEXT = {"kind": "text", "content": "Get 5.99% APR, guaranteed approval!",
        "title": "atomicity", "target_jurisdictions": ["US-CA"]}


def _balance(org: str) -> int:
    row = q_one("select subscription_credits + purchased_credits as t "
                "from public.credit_balances where org_id = %s", (org,))
    return row["t"] if row else 0


async def test_fault_between_charge_and_enqueue_rolls_back_both(dbpool, tenant):
    org, owner = tenant["org"], tenant["users"]["owner"]
    before = _balance(org)
    run_id = str(uuid.uuid4())
    with pytest.raises(RuntimeError, match="injected"):
        async with adb.transaction() as conn:
            await conn.execute(
                "insert into public.submissions (id, org_id, created_by, title) "
                "values (%s, %s, %s, 'fault')",
                (run_id, org, owner))  # reuse uuid as submission id for brevity
            await conn.execute(
                "insert into public.analysis_runs (id, submission_id, org_id, status) "
                "values (%s, %s, %s, 'queued')", (run_id, run_id, org))
            cur = await conn.execute(
                "select app.consume_credits(%s, %s, 5) as d", (org, run_id))
            assert (await cur.fetchone())["d"]["allowed"]
            raise RuntimeError("injected fault BETWEEN charge and enqueue")
    assert _balance(org) == before                                # charge rolled back
    assert q_one("select count(*) as n from public.credit_ledger "
                 "where run_id = %s", (run_id,))["n"] == 0
    assert q_one("select count(*) as n from app.job_queue "
                 "where run_id = %s", (run_id,))["n"] == 0
    assert q_one("select count(*) as n from public.analysis_runs "
                 "where id = %s", (run_id,))["n"] == 0             # rows too


async def test_route_level_fault_keeps_money_safe(client, tenant, monkeypatch):
    async def boom(conn, run_id):
        raise RuntimeError("enqueue exploded")
    monkeypatch.setattr(queue, "enqueue_tx", boom)
    org = tenant["org"]
    before = _balance(org)
    tok = mint_jwt(tenant["users"]["reviewer"], f"reviewer-{tenant['tag']}@bt.local")
    r = await client.post("/v1/submissions", json=TEXT, headers=auth(tok, org))
    assert r.status_code == 500
    assert _balance(org) == before
    assert q_all("select 1 from public.submissions where org_id = %s "
                 "and title = 'atomicity'", (org,)) == []


async def test_submit_202_then_402_then_idempotent_replay(client, tenant):
    org = tenant["org"]
    tok = mint_jwt(tenant["users"]["reviewer"], f"reviewer-{tenant['tag']}@bt.local")
    hdrs = auth(tok, org) | {"Idempotency-Key": f"idem-{tenant['tag']}"}

    r1 = await client.post("/v1/submissions", json=TEXT, headers=hdrs)
    assert r1.status_code == 202, r1.text
    body = r1.json()
    # 0012: the base price is the FLOOR of the charge, escrowed together with a
    # forecast for model usage. The final charge lands at settle, not here.
    assert body["credits_floor"] == 1                       # free text price
    assert body["credits_reserved"] >= body["credits_floor"]
    assert q_one("select status from app.job_queue where run_id = %s",
                 (body["run_id"],))["status"] == "queued"
    audited = q_all("select action from public.audit_logs where org_id = %s "
                    "and action in ('submission.created','credits.reserved')",
                    (org,))
    assert len(audited) >= 2

    # same key → replayed response, no second reserve
    r2 = await client.post("/v1/submissions", json=TEXT, headers=hdrs)
    assert r2.status_code == 202 and r2.json()["run_id"] == body["run_id"]
    assert q_one("select count(*) as n from public.credit_holds where org_id = %s",
                 (org,))["n"] == 1

    # same key, different body → 409
    r3 = await client.post("/v1/submissions",
                           json=TEXT | {"content": "different creative"},
                           headers=hdrs)
    assert r3.status_code == 409

    # drain the balance → 402 with the §11 error shape, run recorded + audited
    q_one("select app.adjust_credits_manual(%s, -%s, 'subscription', null, 'drain') as x",
          (org, _balance(org)))
    r4 = await client.post("/v1/submissions", json=TEXT, headers=auth(tok, org))
    assert r4.status_code == 402
    err = r4.json()["error"]
    assert err["code"] == "insufficient_credits"
    assert err["details"]["needed"] == 1 and err["details"]["balance"] == 0
    rejected = q_one(
        "select count(*) as n from public.analysis_runs "
        "where org_id = %s and status = 'failed' and error like 'rejected:%%'",
        (org,))["n"]
    assert rejected == 1
    assert q_one("select count(*) as n from public.audit_logs where org_id = %s "
                 "and action = 'run.quota_rejected'", (org,))["n"] == 1

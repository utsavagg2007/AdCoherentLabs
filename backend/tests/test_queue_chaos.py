"""Queue chaos (§16): dead worker → lease expiry → watchdog requeue →
completes; forced failures → DLQ + refund; fairness + concurrency wall."""

from __future__ import annotations

import pytest

from .conftest import q_all, q_one, set_tier

pytestmark = pytest.mark.needs_db


def _run(org: str, user: str) -> str:
    sub = q_one("insert into public.submissions (org_id, created_by, title) "
                "values (%s, %s, 'chaos') returning id::text", (org, user))["id"]
    run = q_one("insert into public.analysis_runs (submission_id, org_id, status) "
                "values (%s, %s, 'queued') returning id::text", (sub, org))["id"]
    q_one("select app.enqueue_run(%s) as j", (run,))
    return run


def test_dead_worker_lease_reclaim_then_dlq_refunds(tenant):
    org, owner = tenant["org"], tenant["users"]["owner"]
    run = _run(org, owner)
    q_one("select app.consume_credits(%s, %s, 3) as d", (org, run))

    # attempts 1..3: lease, then die (simulate by forcing the lease to expire)
    for attempt in (1, 2, 3):
        job = q_one("select * from app.lease_job('chaos-worker')")
        assert job and str(job["run_id"]) == run and job["attempts"] == attempt
        q_one("update app.job_queue set lease_expires_at = now() - interval '1s' "
              "where id = %s returning id", (job["id"],))
        reclaimed = q_all("select * from app.requeue_expired_jobs()")
        mine = [r for r in reclaimed if str(r["run_id"]) == run]
        assert len(mine) == 1
        expected = "dlq" if attempt == 3 else "requeued"
        assert mine[0]["disposition"] == expected
        if expected == "requeued":
            q_one("update app.job_queue set not_before = now() "
                  "where run_id = %s returning id", (run,))

    # watchdog's DLQ → the refund is idempotent and ledger-derived
    refund = q_one("select app.refund_credits(%s, %s) as r", (org, run))["r"]
    assert refund["refunded"] == 3
    assert q_one("select app.refund_credits(%s, %s) as r", (org, run))["r"]["refunded"] == 0
    assert q_all("select * from app.reconcile_credit_balances() where org_id = %s",
                 (org,)) == []


def test_fail_job_backoff_then_dlq_disposition(tenant):
    org, owner = tenant["org"], tenant["users"]["owner"]
    run = _run(org, owner)
    j1 = q_one("select * from app.lease_job('w1')")
    d1 = q_one("select app.fail_job(%s, 'w1', 'boom') as d", (j1["id"],))["d"]
    assert d1["disposition"] == "requeued" and d1["retry_in_seconds"] == 60
    assert q_one("select * from app.lease_job('w1')") is None      # backoff gate
    q_one("update app.job_queue set not_before = now() where id = %s returning id",
          (j1["id"],))
    q_one("select * from app.lease_job('w1')")
    d2 = q_one("select app.fail_job(%s, 'w1', 'boom') as d", (j1["id"],))["d"]
    assert d2["disposition"] == "requeued" and d2["retry_in_seconds"] == 300
    q_one("update app.job_queue set not_before = now() where id = %s returning id",
          (j1["id"],))
    q_one("select * from app.lease_job('w1')")
    d3 = q_one("select app.fail_job(%s, 'w1', 'boom') as d", (j1["id"],))["d"]
    assert d3["disposition"] == "dlq"
    # admin requeue resets attempts
    assert q_one("select app.requeue_dlq_job(%s) as ok", (j1["id"],))["ok"]
    assert q_one("select attempts, status from app.job_queue where id = %s",
                 (j1["id"],)) == {"attempts": 0, "status": "queued"}


def test_org_concurrency_wall_and_fencing(tenant):
    org, owner = tenant["org"], tenant["users"]["owner"]
    set_tier(org, "free")                       # max_concurrent_runs = 1
    _run(org, owner)
    _run(org, owner)
    j1 = q_one("select * from app.lease_job('wa')")
    assert j1 is not None
    assert q_one("select * from app.lease_job('wb')") is None   # wall holds
    # fencing: wb cannot heartbeat/complete/fail wa's lease
    assert q_one("select app.heartbeat_job(%s, 'wb') as x", (j1["id"],))["x"] is None
    assert q_one("select app.complete_job(%s, 'wb') as x", (j1["id"],))["x"] is None
    assert q_one("select app.fail_job(%s, 'wb', 'steal') as x",
                 (j1["id"],))["x"]["disposition"] == "not_owner"
    assert q_one("select app.complete_job(%s, 'wa') as x", (j1["id"],))["x"]
    assert q_one("select * from app.lease_job('wb')") is not None  # next job flows


def test_release_does_not_burn_an_attempt(tenant):
    org, owner = tenant["org"], tenant["users"]["owner"]
    run = _run(org, owner)
    j = q_one("select * from app.lease_job('wr')")
    assert j["attempts"] == 1
    q_one("select app.release_job(%s, 'wr', 0) as x", (j["id"],))
    j2 = q_one("select * from app.lease_job('wr')")
    assert str(j2["run_id"]) == run and j2["attempts"] == 1      # not 2

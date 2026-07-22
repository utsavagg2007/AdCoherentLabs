"""E2E with stub LLM (§16): submit text via the API → worker leases and runs
REAL Layers 1/2/4 (stub Layer 3, zero API spend) → statuses stream → report
persisted → findings queryable → human_review resume round-trips. Extends the
engine saas-selftest contract to the async pipeline.
"""

from __future__ import annotations

import pytest

from .conftest import auth, mint_jwt, q_all, q_one

pytestmark = [pytest.mark.needs_db, pytest.mark.slow]

TEXT = {"kind": "text", "content": "Get 5.99% APR, guaranteed approval!",
        "title": "e2e", "target_jurisdictions": ["US-CA"]}


@pytest.fixture()
def stub_engine(monkeypatch):
    """Patch the executor's Layer-3 seam: real review_and_verify with the
    deterministic stub provider + retriever (no keys, no network)."""
    from engine.orchestrator import review_and_verify as real_rv
    from engine.orchestrator import resume_with_human_guidance as real_resume
    from engine.saas_selftest import ClearProvider
    from engine.selftest import StubProvider, stub_retriever

    from worker import executor

    state = {"mode": "clear"}

    def rv(asset, tier, **kw):
        provider = (ClearProvider() if state["mode"] == "clear"
                    else StubProvider(mode="stubborn"))
        return real_rv(asset, tier, provider=provider,
                       retriever=stub_retriever, **kw)

    def resume(asset, guidance, *, product_tier, **kw):
        return real_resume(asset, guidance, product_tier=product_tier,
                           provider=StubProvider(mode="stubborn"),
                           retriever=stub_retriever, **kw)

    monkeypatch.setattr(executor, "review_and_verify", rv)
    monkeypatch.setattr(executor, "resume_with_human_guidance", resume)
    return state


def _work_one(expected_run: str) -> str:
    """Lease + execute exactly one job synchronously (what worker/main.py's
    loop does), returning the engine outcome."""
    from engine.saas import SupabaseDataPlane

    from app.config import settings
    from worker import executor

    db = SupabaseDataPlane(settings.supabase_db_url or None).connect()
    try:
        rows = db._all("select * from app.lease_job('e2e-worker')")
        db.conn.commit()
        assert rows, "nothing to lease"
        job = rows[0]
        job["run_id"], job["org_id"] = str(job["run_id"]), str(job["org_id"])
        assert job["run_id"] == expected_run
        outcome = executor.execute_job(db, job)
        db._exec("select app.complete_job(%s, 'e2e-worker')", (job["id"],))
        return outcome.engine_status
    finally:
        db.close()


async def test_full_async_pipeline(client, tenant, stub_engine):
    org = tenant["org"]
    tok = mint_jwt(tenant["users"]["reviewer"], f"reviewer-{tenant['tag']}@bt.local")

    # 1. submit → 202, charged 1 (free text)
    r = await client.post("/v1/submissions", json=TEXT, headers=auth(tok, org))
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    assert r.json()["credits_charged"] == 1

    # 2. worker executes (stub L3): tier came from the DB, statuses persisted
    assert _work_one(run_id) == "passed"
    run = q_one("select status, tier, engine_run_id, model_id "
                "from public.analysis_runs where id = %s", (run_id,))
    assert run["status"] == "complete" and run["tier"] == "free"
    assert run["engine_run_id"].startswith("run_")
    layers = {r["layer"] for r in q_all(
        "select layer from public.layer_outputs where run_id = %s", (run_id,))}
    assert {"cv", "nlp", "llm", "rule", "report"} <= layers

    # 3. report + findings readable through the API; disclaimer present
    r = await client.get(f"/v1/runs/{run_id}/report", headers=auth(tok, org))
    assert r.status_code == 200
    body = r.json()
    assert body["report"]["status"] == "passed"
    assert "not legal advice" in body["disclaimer"]
    r = await client.get(f"/v1/findings?run_id={run_id}", headers=auth(tok, org))
    assert r.status_code == 200
    findings = r.json()["findings"]
    assert findings, "the guaranteed-approval ad must produce findings"

    # 4. approve a finding (audited)
    r = await client.patch(f"/v1/findings/{findings[0]['id']}",
                           json={"status": "approved"}, headers=auth(tok, org))
    assert r.status_code == 200 and r.json()["finding"]["status"] == "approved"

    # 5. credits: the base charge, optionally followed by the post-run token
    # settlement (0011) — and never a refund (the run succeeded)
    ledger = q_all("select reason from public.credit_ledger where run_id = %s",
                   (run_id,))
    reasons = [l["reason"] for l in ledger]
    assert reasons[0] == "consume.run"
    assert set(reasons) <= {"consume.run", "consume.tokens"}


async def test_human_review_resume_roundtrip(client, tenant, stub_engine):
    org = tenant["org"]
    tok = mint_jwt(tenant["users"]["reviewer"], f"reviewer-{tenant['tag']}@bt.local")

    stub_engine["mode"] = "stubborn"          # L3 exhausts its callback budget
    r = await client.post("/v1/submissions", json=TEXT, headers=auth(tok, org))
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    assert _work_one(run_id) == "human_review"
    assert q_one("select status from public.analysis_runs where id = %s",
                 (run_id,))["status"] == "human_review"

    # resume: 0 credits, new linked run, worker runs ONE steered round
    before = q_one("select subscription_credits + purchased_credits as t "
                   "from public.credit_balances where org_id = %s", (org,))["t"]
    r = await client.post(f"/v1/runs/{run_id}/resume",
                          json={"guidance": "Cover every claim candidate in "
                                            "reviewed_clear."},
                          headers=auth(tok, org))
    assert r.status_code == 202
    resumed_id = r.json()["run_id"]
    assert r.json()["credits_charged"] == 0
    assert _work_one(resumed_id) == "passed"
    row = q_one("select status, resumed_from_run_id::text as parent "
                "from public.analysis_runs where id = %s", (resumed_id,))
    assert row == {"status": "complete", "parent": run_id}
    after = q_one("select subscription_credits + purchased_credits as t "
                  "from public.credit_balances where org_id = %s", (org,))["t"]
    assert after == before                     # the resume was free

    # a resume of a non-human_review run is refused
    r = await client.post(f"/v1/runs/{resumed_id}/resume",
                          json={"guidance": "again"}, headers=auth(tok, org))
    assert r.status_code == 409

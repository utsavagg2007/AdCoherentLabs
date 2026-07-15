"""LIVE Supabase integration proof for the tenant-scoped engine.

Runs against the real self-hosted stack (SUPABASE_DB_URL / DATABASE_URL)
with a deterministic stub standing in for the Layer-3 LLM — no API spend,
but every SaaS integration point is exercised for real:

  A. schema preflight — migrations 0001..0007 applied, plan_entitlements
     in lockstep with the engine's compiled TIERS (zero drift);
  B. provisioning — throwaway org + users (owner, viewer, unconfirmed);
  C. tier fetch — the engine runs on app.org_tier(org): free by default,
     and flipping the subscription row to 'pro' re-routes the next run
     with NO code or config change;
  D. security gates — non-member org selection, sub-reviewer role, and
     unconfirmed email are all refused BEFORE any layer runs;
  E. full persisted run — analysis_runs lifecycle, 4 layer_outputs,
     findings, scan + token_spend usage_events, audit trail;
  F. framework entitlements — a free-tier run reviews only the plan's
     frameworks (plan_entitlements.frameworks scopes routing);
  G. operator interference — a stubborn LLM exhausts its callback budget
     (DB status human_review), resume_run persists the guided round as a
     linked run (resumed_from_run_id);
  H. quota — the monthly cap rejects the run BEFORE the layers, with a
     failed run row and a run.quota_rejected audit event;
  I. API keys — sha256-at-rest issuance gated on the api_access
     entitlement, verification, scope check, revocation;
  J. audit hash chain — app.verify_audit_chain() finds no broken links;
  K. RLS isolation — supabase/tests/rls_isolation_test.sql still passes
     on this stack (cross-tenant reads/writes impossible);
  L. realtime — analysis_runs/findings still in the publication.

The throwaway org is deleted afterwards (cascade cleans every child row);
audit_logs rows remain by design — the log is append-only.

Run:  python -m engine.cli saas-selftest
"""

from __future__ import annotations

import sys
import uuid

from . import _paths  # noqa: F401  (sys.path bootstrap - must be first)

import psycopg
from psycopg.rows import dict_row

from ._paths import PROJECT_ROOT
from .saas import (
    ApiKeyError,
    PermissionDeniedError,
    QuotaExceededError,
    SupabaseDataPlane,
    run_for_user,
    resume_run,
)
from .selftest import StubProvider, _clear_review, _extract_asset, stub_retriever
from .tiers import TIERS

AD_TEXT = "Get 5.99% APR, guaranteed approval!"
RLS_TEST_SQL = PROJECT_ROOT / "supabase" / "tests" / "rls_isolation_test.sql"


class ClearProvider(StubProvider):
    """Always returns a complete, sound review (round-1 pass)."""

    def complete(self, tier, system, user):
        from adcoherent_rag.review.providers import CompletionResult

        self.prompts.append(user)
        return CompletionResult(payload=_clear_review(_extract_asset(user)),
                                model="stub-compliance-llm",
                                input_tokens=100, output_tokens=50)


def _provision(db: SupabaseDataPlane, tag: str) -> dict:
    """Throwaway tenant: org + free sub + owner/viewer/unconfirmed users."""
    conn = db.conn
    ids = {}
    with conn.cursor() as cur:
        for key, email, confirmed in (
                ("owner", f"owner-{tag}@selftest.local", True),
                ("viewer", f"viewer-{tag}@selftest.local", True),
                ("unconfirmed", f"unconfirmed-{tag}@selftest.local", False)):
            cur.execute(
                "insert into auth.users (instance_id, id, aud, role, email, "
                "  email_confirmed_at, created_at, updated_at) "
                "values ('00000000-0000-0000-0000-000000000000', "
                "  gen_random_uuid(), 'authenticated', 'authenticated', %s, "
                "  case when %s then now() end, now(), now()) "
                "returning id::text", (email, confirmed))
            ids[key] = cur.fetchone()["id"]
        cur.execute("insert into public.orgs (name) values (%s) "
                    "returning id::text", (f"engine-saas-selftest-{tag}",))
        ids["org"] = cur.fetchone()["id"]
        cur.execute(
            "insert into public.memberships (org_id, user_id, role) values "
            "(%(org)s, %(owner)s, 'owner'), (%(org)s, %(viewer)s, 'viewer'), "
            "(%(org)s, %(unconfirmed)s, 'reviewer')", ids)
        cur.execute(
            "insert into public.subscriptions (org_id, tier, status, "
            "  current_period_start, current_period_end) "
            "values (%s, 'free', 'active', date_trunc('month', now()), "
            "  date_trunc('month', now()) + interval '1 month')", (ids["org"],))
    conn.commit()
    return ids


def _set_tier(db: SupabaseDataPlane, org: str, tier: str) -> None:
    db._exec("update public.subscriptions set tier = %s where org_id = %s",
             (tier, org))


def _cleanup(db_url: str, ids: dict) -> None:
    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            if "org" in ids:
                cur.execute("delete from public.orgs where id = %s",
                            (ids["org"],))
            for key in ("owner", "viewer", "unconfirmed"):
                if key in ids:
                    cur.execute("delete from auth.users where id = %s",
                                (ids[key],))


def main() -> int:  # noqa: C901 - one linear proof, deliberately verbose
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        status = "PASS" if cond else "FAIL"
        print(f"  [{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
        if not cond:
            failures.append(name)

    tag = uuid.uuid4().hex[:8]
    db = SupabaseDataPlane().connect()
    print(f"connected: {db.db_url.split('@')[-1]}  (tenant tag {tag})")
    ids: dict = {}
    try:
        print("== A. schema preflight ==")
        migs = {r["filename"] for r in db._all(
            "select filename from app.schema_migrations")}
        check("migrations 0001..0007 applied",
              all(any(m.startswith(f"000{i}") for m in migs) for i in range(1, 8)),
              f"found: {sorted(migs)}")
        rows = db._all("select * from public.plan_entitlements")
        drift = []
        for r in rows:
            t = TIERS.get(r["tier"])
            if t is None or (t.provider, t.model, t.max_output_tokens) != (
                    r["llm_provider"], r["llm_model"], r["max_output_tokens"]):
                drift.append(r["tier"])
        check("plan_entitlements matches engine TIERS for all 5 tiers",
              len(rows) == 5 and not drift, f"drift in: {drift}")

        print("== B. provision throwaway tenant ==")
        ids = _provision(db, tag)
        check("org + 3 users created", bool(ids.get("org")))

        print("== C. tier is fetched from the DB ==")
        ent = db.get_entitlements(ids["org"])
        check("fresh org resolves to free tier", ent.tier == "free", ent.tier)
        check("free plan scopes frameworks (not 'all')",
              isinstance(ent.frameworks, list), repr(ent.frameworks))
        _set_tier(db, ids["org"], "pro")
        ent = db.get_entitlements(ids["org"])
        check("subscription row change re-routes the engine: pro",
              ent.tier == "pro" and ent.llm_model == "claude-sonnet-5",
              f"{ent.tier}/{ent.llm_model}")
        check("no entitlement drift", not ent.drift, str(ent.drift))

        print("== D. security gates (refused before any layer runs) ==")
        other_org = str(uuid.uuid4())
        for name, kwargs, exc in (
                ("non-member org id refused",
                 dict(user=ids["owner"], org=other_org), PermissionDeniedError),
                ("viewer role cannot submit",
                 dict(user=ids["viewer"]), PermissionDeniedError),
                ("unconfirmed email cannot submit",
                 dict(user=ids["unconfirmed"]), PermissionDeniedError)):
            try:
                run_for_user(text=AD_TEXT, provider=ClearProvider(),
                             retriever=stub_retriever, db=db, **kwargs)
                check(name, False, "no exception raised")
            except exc:
                check(name, True)

        print("== E. full persisted run (tier pro, from the DB) ==")
        result = run_for_user(
            user=ids["owner"], text=AD_TEXT, title="selftest ad",
            target_jurisdictions=["US-CA"],
            provider=ClearProvider(), retriever=stub_retriever, db=db)
        saas = result.provenance["saas"]
        check("engine ran on the DB tier", result.tier == "pro", result.tier)
        check("run passed round 1", result.status == "passed", result.status)
        run_row = db.find_run(saas["analysis_run_id"])
        check("analysis_runs row complete + engine_run_id stamped",
              run_row["status"] == "complete"
              and run_row["engine_run_id"] == result.run_id
              and run_row["tier"] == "pro",
              str({k: run_row[k] for k in ("status", "engine_run_id", "tier")}))
        n_layers = db._one(
            "select count(distinct layer) as n from public.layer_outputs "
            "where run_id = %s", (saas["analysis_run_id"],))["n"]
        check("all four layer outputs persisted", n_layers == 4, f"layers={n_layers}")
        n_findings = db._one(
            "select count(*) as n from public.findings where run_id = %s",
            (saas["analysis_run_id"],))["n"]
        expected = (len(result.llm_review.get("findings", []))
                    + len(result.verification.asset_defects
                          if result.verification else []))
        check("LLM findings + rule-engine asset defects persisted as rows",
              n_findings == expected, f"db={n_findings} expected={expected}")
        usage = {r["kind"] for r in db._all(
            "select kind from public.usage_events where org_id = %s",
            (ids["org"],))}
        check("token_spend metered", "token_spend" in usage, str(usage))
        charged = db._one(
            "select coalesce(sum(-delta), 0) as n from public.credit_ledger "
            "where run_id = %s and reason = 'consume.run'",
            (saas["analysis_run_id"],))["n"]
        check("run charged its published credit price (pro text = 5)",
              charged == 5, f"charged={charged}")
        actions = {r["action"] for r in db._all(
            "select action from public.audit_logs where org_id = %s",
            (ids["org"],))}
        check("lifecycle audited",
              {"submission.created", "run.started", "run.completed"} <= actions,
              str(actions))

        print("== F. framework entitlements scope the review (free tier) ==")
        _set_tier(db, ids["org"], "free")
        result_f = run_for_user(
            user=ids["owner"], text=AD_TEXT, target_jurisdictions=["US-CA"],
            provider=ClearProvider(), retriever=stub_retriever, db=db)
        stored = db.load_asset_representation(
            result_f.provenance["saas"]["analysis_run_id"])
        routed = [str(f).upper()
                  for f in (stored.get("routing") or {}).get("frameworks", [])]
        allowed = {str(f).upper()
                   for f in db.get_entitlements(ids["org"]).frameworks}
        check("free run reviews only plan frameworks",
              result_f.tier == "free" and set(routed) <= allowed,
              f"routed={routed} allowed={sorted(allowed)}")
        check("dropped frameworks surfaced as a warning",
              any("plan" in w for w in result_f.warnings) or set(routed) == allowed,
              str(result_f.warnings))

        print("== G. operator interference, persisted ==")
        result_g = run_for_user(
            user=ids["owner"], text=AD_TEXT,
            provider=StubProvider(mode="stubborn"), retriever=stub_retriever,
            db=db)
        check("stubborn LLM exhausts budget -> human_review",
              result_g.status == "human_review", result_g.status)
        g_run = db.find_run(result_g.provenance["saas"]["analysis_run_id"])
        check("DB status human_review (first-class)",
              g_run["status"] == "human_review", g_run["status"])
        resumed = resume_run(
            user=ids["owner"], run=g_run["id"],
            guidance="Cover every claim candidate in reviewed_clear.",
            provider=StubProvider(mode="stubborn"), retriever=stub_retriever,
            db=db)
        check("guided resume passes", resumed.status == "passed", resumed.status)
        r_run = db.find_run(resumed.provenance["saas"]["analysis_run_id"])
        check("resume linked to original run",
              r_run["resumed_from_run_id"] == g_run["id"],
              str(r_run["resumed_from_run_id"]))

        print("== H. the credit gate rejects BEFORE the layers ==")
        bal = db.credit_balance(ids["org"])
        with db.conn.cursor() as cur:   # drain both buckets to exactly zero
            if bal["subscription_credits"]:
                cur.execute("select app.adjust_credits_manual(%s, %s, "
                            "'subscription', null, 'selftest drain')",
                            (ids["org"], -bal["subscription_credits"]))
            if bal["purchased_credits"]:
                cur.execute("select app.adjust_credits_manual(%s, %s, "
                            "'purchased', null, 'selftest drain')",
                            (ids["org"], -bal["purchased_credits"]))
        db.conn.commit()
        try:
            run_for_user(user=ids["owner"], text=AD_TEXT,
                         provider=ClearProvider(), retriever=stub_retriever,
                         db=db)
            check("run over balance rejected", False, "no exception")
        except QuotaExceededError as exc:
            check("run over balance rejected (needed > balance)",
                  getattr(exc, "needed", 0) > getattr(exc, "balance", 0),
                  str(exc))
        check("rejection audited", "run.quota_rejected" in {
            r["action"] for r in db._all(
                "select action from public.audit_logs where org_id = %s",
                (ids["org"],))})

        print("== M. credit system contract (migration 0008) ==")
        _set_tier(db, ids["org"], "free")
        c_free_text = db.credit_cost(ids["org"], "text")
        _set_tier(db, ids["org"], "pro")
        c_pro_image = db.credit_cost(ids["org"], "image")
        _set_tier(db, ids["org"], "design")
        c_design_car3 = db.credit_cost(ids["org"], "carousel", 3)
        check("published cost matrix (free text 1 / pro image 10 / "
              "design 3-card carousel 40)",
              (c_free_text, c_pro_image, c_design_car3) == (1, 10, 40),
              f"got {(c_free_text, c_pro_image, c_design_car3)}")
        _set_tier(db, ids["org"], "pro")
        grant = db._one("select app.grant_purchased_credits(%s, 100, %s) as g",
                        (ids["org"], f"selftest-pack-{tag}"))["g"]
        db.conn.commit()
        regrant = db._one("select app.grant_purchased_credits(%s, 100, %s) as g",
                          (ids["org"], f"selftest-pack-{tag}"))["g"]
        db.conn.commit()
        check("pack grant idempotent by stripe_ref",
              grant["granted"] and not regrant["granted"], str(regrant))
        db._exec("select app.adjust_credits_manual(%s, 2, 'subscription', "
                 "null, 'selftest spend-order')", (ids["org"],))
        m_sub = db.create_submission(ids["org"], ids["owner"], "spend-order")
        m_run = db.create_run(m_sub, ids["org"], "pro", "claude-sonnet-5")
        decision = db.consume_credits(ids["org"], m_run, 5)
        check("allowance spent before packs (2 sub + 3 pack)",
              decision["sub_bal"] == 0 and decision["pack_bal"] == 97,
              str(decision))
        refund = db.refund_credits(ids["org"], m_run)
        again = db.refund_credits(ids["org"], m_run)
        check("system refund reverses per bucket, idempotently",
              refund["subscription"] == 2 and refund["purchased"] == 3
              and again["refunded"] == 0, f"{refund} / {again}")
        drift_rows = db._all(
            "select * from app.reconcile_credit_balances() where org_id = %s",
            (ids["org"],))
        check("ledger sums to balance (reconcile clean)", not drift_rows,
              str(drift_rows))
        q = db.check_quota(ids["org"])
        check("check_quota reports credits for legacy callers",
              q.get("currency") == "credits" and "remaining" in q, str(q))
        _set_tier(db, ids["org"], "free")   # section I expects a free org

        print("== I. API keys (sha256 at rest, entitlement-gated) ==")
        try:
            db.issue_api_key(ids["org"], ids["owner"], "free-should-fail")
            check("free tier refused API key", False, "no exception")
        except PermissionDeniedError:
            check("free tier refused API key", True)
        _set_tier(db, ids["org"], "pro")
        plaintext = db.issue_api_key(ids["org"], ids["owner"], "selftest-key")
        check("key issued", plaintext.startswith("ack_"))
        info = db.verify_api_key(plaintext, scope="submit")
        check("key verifies to its org", info["org_id"] == ids["org"])
        try:
            db.verify_api_key("ack_" + "0" * 48)
            check("wrong key refused", False, "no exception")
        except ApiKeyError:
            check("wrong key refused", True)
        db._exec("update public.api_keys set revoked_at = now() "
                 "where org_id = %s", (ids["org"],))
        try:
            db.verify_api_key(plaintext)
            check("revoked key refused", False, "no exception")
        except ApiKeyError:
            check("revoked key refused", True)

        print("== J. audit hash chain ==")
        broken = db._all("select id from app.verify_audit_chain() where not ok")
        check("chain intact (0 broken links)", not broken,
              f"broken ids: {[r['id'] for r in broken]}")

        print("== K. RLS tenant isolation (the red-line test) ==")
        notices: list[str] = []
        with psycopg.connect(db.db_url, row_factory=dict_row) as rls_conn:
            rls_conn.add_notice_handler(
                lambda d: notices.append(d.message_primary or ""))
            rls_conn.execute(RLS_TEST_SQL.read_text(encoding="utf-8"))
        check("cross-tenant isolation holds",
              any("RLS ISOLATION TEST: PASS" in n for n in notices),
              f"notices: {notices[-3:]}")

        print("== L. realtime publication ==")
        pub = {r["tablename"] for r in db._all(
            "select tablename from pg_publication_tables "
            "where pubname = 'supabase_realtime'")}
        check("analysis_runs + findings published for live UI",
              {"analysis_runs", "findings"} <= pub, str(pub))
    finally:
        db.close()
        try:
            _cleanup(db.db_url, ids)
            print(f"cleanup: org {ids.get('org')} and selftest users deleted "
                  "(audit rows remain by design - the log is append-only)")
        except Exception as exc:  # noqa: BLE001 - report, don't mask the run
            print(f"cleanup FAILED for tag {tag}: {exc} - remove manually",
                  file=sys.stderr)

    print("-" * 60)
    if failures:
        print(f"SAAS SELFTEST: {len(failures)} FAILURE(S): {failures}")
        return 1
    print("SAAS SELFTEST: ALL CHECKS PASSED - the engine is wired to Supabase")
    return 0


if __name__ == "__main__":
    sys.exit(main())

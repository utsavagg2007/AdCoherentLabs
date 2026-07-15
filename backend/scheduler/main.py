"""Scheduler entrypoint (§10/§12/§14/§15): APScheduler running
  * watchdog        every 60 s  — reclaim expired leases; DLQ → refund + alert
  * queue alerts    every 60 s  — DLQ>0, oldest queued >10 min, stale webhooks
  * cycle grants    hourly      — ensure_cycle_grant per org (webhook safety net;
                                  free tiers grant on the calendar month here)
  * idempotency     hourly      — purge expired Idempotency-Key rows
  * retention       daily 03:10 — delete customer content past its window
                                  (free 30 d / paid 90 d); DRY-RUN by default
  * ledger reconcile daily 04:10 — re-sum ledger vs balances, alert on drift
  * audit chain     daily 04:40 — app.verify_audit_chain(), page on break
  * stripe sweep    daily 05:10 — diff Stripe subscriptions vs DB, heal + alert

Run from the repo root:  python -m backend.scheduler.main
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import psycopg  # noqa: E402
import structlog  # noqa: E402
from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: E402
from apscheduler.triggers.cron import CronTrigger  # noqa: E402
from apscheduler.triggers.interval import IntervalTrigger  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.config import settings  # noqa: E402
from app.logging_setup import setup_logging  # noqa: E402
from app.services import storage  # noqa: E402

logger = structlog.get_logger("scheduler")

RETENTION_DAYS = {"free": 30}          # every paid tier: 90 (§14.1)
_DEFAULT_RETENTION = 90


def _conn() -> psycopg.Connection:
    url = settings.database_url_worker or settings.supabase_db_url
    return psycopg.connect(url, row_factory=dict_row, autocommit=True)


# ---------------------------------------------------------------------------

def watchdog() -> None:
    with _conn() as conn:
        rows = conn.execute("select * from app.requeue_expired_jobs()").fetchall()
        for r in rows:
            if r["disposition"] == "dlq":
                run_id, org_id = str(r["run_id"]), str(r["org_id"])
                conn.execute(
                    "update public.analysis_runs set status = 'failed', "
                    "finished_at = now(), error = coalesce(error, 'worker died; "
                    "attempts exhausted') where id = %s", (run_id,))
                refund = conn.execute(
                    "select app.refund_credits(%s, %s) as x",
                    (org_id, run_id)).fetchone()["x"]
                conn.execute(
                    "select app.log_audit_event(%s, null, 'run.failed', %s, %s::jsonb)",
                    (org_id, f"analysis_run:{run_id}",
                     psycopg.types.json.Jsonb({"dlq": True, "watchdog": True,
                                               "refunded": refund.get("refunded", 0)})))
                logger.error("ALERT watchdog.dlq", run_id=run_id, org_id=org_id,
                             refunded=refund.get("refunded", 0))
            else:
                conn.execute(
                    "update public.analysis_runs set status = 'queued' "
                    "where id = %s and status not in "
                    "('complete','failed','human_review')", (str(r["run_id"]),))
                logger.warning("watchdog.requeued", run_id=str(r["run_id"]))


def queue_alerts() -> None:
    with _conn() as conn:
        stats = conn.execute("select app.queue_stats() as s").fetchone()["s"]
        if stats["dlq"] > 0:
            logger.error("ALERT queue.dlq_nonzero", **stats)
        if stats["oldest_queued_seconds"] > 600:
            logger.error("ALERT queue.oldest_exceeds_10min", **stats)
        stale = conn.execute(
            "select count(*) as n from app.billing_events "
            "where processed_at is null and received_at < now() - interval '10 minutes'"
        ).fetchone()["n"]
        if stale:
            logger.error("ALERT stripe.webhooks_stuck", count=stale)


def cycle_grants_sweep() -> None:
    granted = 0
    with _conn() as conn:
        orgs = conn.execute("select id::text from public.orgs").fetchall()
        for o in orgs:
            out = conn.execute("select app.ensure_cycle_grant(%s) as g",
                               (o["id"],)).fetchone()["g"]
            granted += 1 if out.get("granted") else 0
    if granted:
        logger.info("grants.swept", granted=granted, orgs=len(orgs))


def purge_idempotency() -> None:
    with _conn() as conn:
        n = conn.execute(
            "select app.purge_expired_idempotency_keys() as n").fetchone()["n"]
        if n:
            logger.info("idempotency.purged", rows=n)


def retention_sweep() -> None:
    """Customer content past its window: delete the storage object, keep the
    derived work product (findings/reports are the auditable asset customers
    pay for — §14.1). DRY-RUN until RETENTION_DRY_RUN=false (P9 gate)."""
    with _conn() as conn:
        rows = conn.execute(
            "select a.id::text, a.org_id::text, a.storage_path, "
            "       app.org_tier(a.org_id) as tier "
            "from public.assets a "
            "where a.storage_path is not null "
            "  and a.created_at < now() - make_interval(days => case "
            "        when app.org_tier(a.org_id) = 'free' then %s else %s end)",
            (RETENTION_DAYS["free"], _DEFAULT_RETENTION)).fetchall()
        if not rows:
            return
        if settings.retention_dry_run:
            logger.warning("retention.dry_run - would delete objects",
                           candidates=len(rows))
            return
        deleted = 0
        for r in rows:
            if storage.delete_object_sync(r["storage_path"]):
                conn.execute(
                    "update public.assets set storage_path = null where id = %s",
                    (r["id"],))
                conn.execute(
                    "select app.log_audit_event(%s, null, "
                    "'data.retention_deleted', %s, %s::jsonb)",
                    (r["org_id"], f"asset:{r['id']}",
                     psycopg.types.json.Jsonb({"tier": r["tier"]})))
                deleted += 1
        logger.info("retention.deleted", objects=deleted, candidates=len(rows))


def ledger_reconcile() -> None:
    with _conn() as conn:
        drift = conn.execute("select * from app.reconcile_credit_balances()").fetchall()
        if drift:
            logger.error("ALERT credits.reconcile_drift", rows=[dict(d) for d in drift])
            for d in drift:
                conn.execute(
                    "select app.log_audit_event(%s, null, "
                    "'credits.reconcile_drift', null, %s::jsonb)",
                    (str(d["org_id"]),
                     psycopg.types.json.Jsonb({"bucket": d["bucket"],
                                               "ledger_sum": int(d["ledger_sum"]),
                                               "stored": d["stored"]})))
        else:
            logger.info("credits.reconcile_clean")


def audit_chain_verify() -> None:
    with _conn() as conn:
        broken = conn.execute(
            "select id from app.verify_audit_chain() where not ok limit 10").fetchall()
        if broken:
            logger.critical("ALERT audit.chain_broken",
                            ids=[b["id"] for b in broken])
        else:
            logger.info("audit.chain_intact")


def stripe_sweep() -> None:
    if not settings.stripe_secret_key:
        return
    import asyncio

    from app import db as adb
    from app.services import stripe_sync

    async def run():
        await adb.open_pool()
        try:
            return await stripe_sync.reconcile_sweep()
        finally:
            await adb.close_pool()

    out = asyncio.run(run())
    logger.info("stripe.sweep_done", **(out or {}))


def main() -> int:
    setup_logging(settings.log_level, sentry_dsn=settings.sentry_dsn,
                  component="scheduler")
    logger.info("scheduler.boot", retention_dry_run=settings.retention_dry_run)
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(watchdog, IntervalTrigger(seconds=60), id="watchdog",
                  coalesce=True, max_instances=1)
    sched.add_job(queue_alerts, IntervalTrigger(seconds=60), id="alerts",
                  coalesce=True, max_instances=1)
    sched.add_job(cycle_grants_sweep, CronTrigger(minute=5), id="grants",
                  coalesce=True, max_instances=1)
    sched.add_job(purge_idempotency, CronTrigger(minute=35), id="idempotency")
    sched.add_job(retention_sweep, CronTrigger(hour=3, minute=10), id="retention")
    sched.add_job(ledger_reconcile, CronTrigger(hour=4, minute=10), id="reconcile")
    sched.add_job(audit_chain_verify, CronTrigger(hour=4, minute=40), id="chain")
    sched.add_job(stripe_sweep, CronTrigger(hour=5, minute=10), id="stripe")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler.stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())

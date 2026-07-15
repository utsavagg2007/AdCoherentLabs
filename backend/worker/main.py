"""Worker entrypoint: lease → execute → complete/fail, heartbeating (§10).

One leased run per process (engine layers are CPU-heavy in L1, IO-heavy in
L3); scale = container replicas. SIGTERM → stop leasing, finish the current
run, exit — deploys never kill runs (stop_grace_period covers the drain).

Run from the repo root (the engine repos must be importable):
    python -m backend.worker.main            # or: python backend/worker/main.py
"""

from __future__ import annotations

import os
import signal
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

# repo root on sys.path so `engine` (and its layer repos) import
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import structlog  # noqa: E402

from app.config import settings  # noqa: E402
from app.logging_setup import setup_logging  # noqa: E402

logger = structlog.get_logger("worker.main")

_stop = threading.Event()


def _worker_id() -> str:
    return (f"{settings.worker_id_prefix}-{socket.gethostname()}"
            f"-{os.getpid()}-{uuid.uuid4().hex[:6]}")


class Heartbeat(threading.Thread):
    """Extends the lease every HEARTBEAT_SECONDS while the run executes.
    Stops extending past RUN_MAX_SECONDS — a hung run then loses its lease
    and the watchdog requeues it (the fencing in app.heartbeat_job/complete_job
    makes the stale worker's later writes no-ops)."""

    def __init__(self, db, job_id: int, worker_id: str):
        super().__init__(daemon=True)
        self.db, self.job_id, self.worker_id = db, job_id, worker_id
        self.done = threading.Event()
        self.started_at = time.monotonic()

    def run(self):
        import psycopg
        while not self.done.wait(settings.heartbeat_seconds):
            if time.monotonic() - self.started_at > settings.run_max_seconds:
                logger.error("heartbeat.budget_exhausted - abandoning lease",
                             job_id=self.job_id)
                return
            try:
                with psycopg.connect(self.db, autocommit=True) as conn:
                    conn.execute("select app.heartbeat_job(%s, %s, %s)",
                                 (self.job_id, self.worker_id,
                                  settings.lease_seconds))
            except Exception as exc:
                logger.warning("heartbeat.failed", job_id=self.job_id,
                               error=str(exc))


def main() -> int:
    setup_logging(settings.log_level, sentry_dsn=settings.sentry_dsn,
                  component="worker")
    from engine.saas import SupabaseDataPlane  # heavy import after logging
    from . import executor

    worker_id = _worker_id()
    logger.info("worker.boot", worker_id=worker_id,
                lease_seconds=settings.lease_seconds)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, lambda *_: _stop.set())
        except (ValueError, OSError):   # not main thread / unsupported on win
            pass

    db = SupabaseDataPlane(settings.supabase_db_url or None).connect()
    db_url = db.db_url

    while not _stop.is_set():
        try:
            rows = db._all("select * from app.lease_job(%s, %s)",
                           (worker_id, settings.lease_seconds))
            db.conn.commit()
        except Exception as exc:
            logger.error("lease.failed", error=str(exc))
            db.close()
            time.sleep(5)
            db = SupabaseDataPlane(db_url).connect()
            continue

        if not rows:
            _stop.wait(settings.worker_poll_seconds)
            continue

        job = rows[0]
        job["run_id"], job["org_id"] = str(job["run_id"]), str(job["org_id"])
        log = logger.bind(job_id=job["id"], run_id=job["run_id"],
                          attempt=job["attempts"])
        log.info("job.leased", tier=job["tier"])
        hb = Heartbeat(db_url, job["id"], worker_id)
        hb.start()
        try:
            outcome = executor.execute_job(db, job)
            db._exec("select app.complete_job(%s, %s)", (job["id"], worker_id))
            log.info("job.complete", engine_status=outcome.engine_status)
        except (executor.BreakerOpen, executor.NoProviderSlot) as exc:
            delay = 60 if isinstance(exc, executor.BreakerOpen) else 15
            db._exec("select app.release_job(%s, %s, %s)",
                     (job["id"], worker_id, delay))
            log.info("job.released", reason=str(exc), retry_in=delay)
        except Exception as exc:  # noqa: BLE001 - taxonomy decides (§10.3)
            err = f"{type(exc).__name__}: {exc}"
            log.warning("job.attempt_failed", error=err[:500])
            try:
                row = db._one("select app.fail_job(%s, %s, %s) as d",
                              (job["id"], worker_id, err))
                db.conn.commit()
                disposition = (row or {}).get("d") or {}
                if disposition.get("disposition") == "dlq":
                    executor.finalize_dlq(db, job["org_id"], job["run_id"], err)
                elif disposition.get("disposition") == "requeued":
                    executor.requeue_run(db, job["run_id"], err)
            except Exception:
                log.exception("job.fail_handling_crashed")
                db.close()
                db = SupabaseDataPlane(db_url).connect()
        finally:
            hb.done.set()

    logger.info("worker.drained - exiting cleanly", worker_id=worker_id)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

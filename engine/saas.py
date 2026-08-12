"""Supabase data plane: the engine run as a tenant-scoped SaaS operation.

This module is the bridge between the 4-layer engine (pure compute) and
the self-hosted Supabase stack (identity, tenancy, entitlements, quota,
persistence, audit). The contract, per the Build Playbook and supabase.md:

  * The product tier is FETCHED FROM THE DATABASE for every run —
    ``app.org_tier(org)`` over the Stripe-synced ``subscriptions`` row —
    never taken from the caller. A client-supplied tier cannot exist here.
  * The org is derived from the user's ``memberships`` row. A caller may
    *narrow* to one of their orgs, but membership is always re-verified:
    client-supplied org ids are treated as hostile until proven joined.
  * Analysis requires a confirmed email and reviewer+ role (Phase 3).
  * Quota is consumed atomically (``app.consume_scan_quota``) BEFORE any
    expensive layer runs; a denied run is recorded and rejected.
  * Per-tier framework entitlements (``plan_entitlements.frameworks``)
    scope the review: frameworks the plan does not include are removed
    from routing before Layer 3 (checks are framework-scoped, so their
    deterministic rules drop out with them).
  * Every run writes: ``submissions`` -> ``assets`` -> ``analysis_runs``
    (live status transitions for Realtime) -> ``layer_outputs`` (all four
    layers) -> ``findings`` -> ``usage_events`` (scan + token spend), and
    hash-chained ``audit_logs`` events at each lifecycle edge.
  * This module connects as a privileged DB role that BYPASSES RLS, so
    every statement sets ``org_id`` explicitly — there is no DB safety
    net behind a bug here. Keep it server-side; never ship its
    connection string or the service key to a client.

Connection: ``SUPABASE_DB_URL`` env var, falling back to ``DATABASE_URL``
(the RAG store string — same Postgres on this stack). Local stack default
is the socat proxy ``postgresql://postgres:...@127.0.0.1:54322/postgres``.

    from engine.saas import run_for_user
    result = run_for_user(user="reviewer@acme.com",
                          text="Get 5.99% APR!", target_jurisdictions=["US-CA"])
    # result.provenance["saas"] -> org, submission, analysis_run ids
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from . import _paths  # noqa: F401  (sys.path bootstrap - must be first)

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .orchestrator import (
    DEFAULT_MAX_LLM_ROUNDS,
    prepare_asset,
    resume_with_human_guidance,
    review_and_verify,
)
from .report import EngineRunResult
from .tiers import TIERS, normalize_tier

logger = logging.getLogger("engine.saas")

#: owner > admin > reviewer > viewer (playbook Phase 3). Submitting an ad
#: for analysis requires reviewer or higher.
ROLE_RANK = {"viewer": 0, "reviewer": 1, "admin": 2, "owner": 3}
SUBMIT_MIN_ROLE = "reviewer"

_VALID_SEVERITIES = {"high", "medium", "low"}
_VALID_VERDICTS = {"potential_violation", "needs_review", "compliant"}
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

#: analysis_runs.status value for each engine outcome. 'human_review' is a
#: first-class DB status (migration 0007): the run is finished computing but
#: not resolved — an operator must resume it.
_RUN_STATUS_BY_ENGINE_STATUS = {
    "passed": "complete",
    "human_review": "human_review",
    "llm_error": "failed",
}


# ---------------------------------------------------------------------------
# Errors — each maps to an HTTP-ish outcome for the API layer above.

class SaasError(RuntimeError):
    """Base for data-plane failures (500 unless subclassed)."""


class NotProvisionedError(SaasError):
    """Unknown user, or user has no org membership (403/404)."""


class MultipleOrgsError(SaasError):
    """User belongs to several orgs and none was selected (400)."""

    def __init__(self, orgs: list[dict]):
        self.orgs = orgs
        names = ", ".join(f"{o['name']} ({o['org_id']})" for o in orgs)
        super().__init__(
            f"user belongs to {len(orgs)} orgs - pass org=<uuid> to pick one: {names}")


class PermissionDeniedError(SaasError):
    """Membership/role/confirmation/entitlement gate failed (403)."""


class QuotaExceededError(SaasError):
    """Monthly scan cap reached — reject BEFORE running the layers (402/409)."""

    def __init__(self, used: int, limit: int | None):
        self.used, self.limit = used, limit
        super().__init__(f"scan quota exhausted: {used}/{limit} used this period")


class InsufficientCreditsError(QuotaExceededError):
    """Credit balance cannot fund the run — reject BEFORE the layers (402).

    Subclasses QuotaExceededError so every existing rejection path (CLI exit
    code 4, run.quota_rejected audit, API 402 mapping) keeps working under
    the credit system (migration 0008, Backend Architecture spec §8).
    """

    def __init__(self, needed: int, balance: int):
        self.needed, self.balance = needed, balance
        # Parent attrs kept meaningful for legacy readers.
        SaasError.__init__(
            self, f"insufficient credits: run costs {needed}, balance is {balance}")
        self.used, self.limit = balance, needed


class ApiKeyError(SaasError):
    """API key unknown, revoked, or not entitled (401/403)."""


# ---------------------------------------------------------------------------
# Entitlements — the DB row that drives the run.

@dataclass(frozen=True)
class Entitlements:
    """One org's resolved plan, straight from Supabase (source of truth).

    ``drift`` lists any disagreement between this row and the engine's
    compiled ``TIERS`` table — a non-empty value means someone changed one
    side without the other (billing/execution mismatch): surface it.
    """

    org_id: str
    tier: str
    llm_provider: str
    llm_model: str
    max_output_tokens: int
    scans_per_month: int | None
    seats: int | None
    api_access: bool
    sso: bool
    sla: bool
    frameworks: Any            # "all" | list[str]
    drift: list[str] = field(default_factory=list)


def _entitlement_drift(tier: str, row: dict) -> list[str]:
    code = TIERS.get(tier)
    if code is None:
        return [f"tier {tier!r} exists in plan_entitlements but not in engine TIERS"]
    drift = []
    for db_field, code_val in (("llm_provider", code.provider),
                               ("llm_model", code.model),
                               ("max_output_tokens", code.max_output_tokens)):
        if row[db_field] != code_val:
            drift.append(f"{db_field}: db={row[db_field]!r} engine={code_val!r}")
    return drift


def _default_db_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL", "")
    if not url:
        # Same resolution the RAG store uses (the repo-root .env is loaded
        # by engine/_paths and again by adcoherent_rag.config on import).
        from adcoherent_rag import config as rag_config
        url = rag_config.DATABASE_URL
    if not url:
        raise SaasError(
            "no Supabase connection string: set SUPABASE_DB_URL or DATABASE_URL "
            "(local stack: postgresql://postgres:<pw>@127.0.0.1:54322/postgres)")
    return url


def _as_uuid(value: str) -> str | None:
    v = str(value).strip()
    return v.lower() if _UUID_RE.match(v) else None


class SupabaseDataPlane:
    """Server-side connection to the SaaS schema (bypasses RLS — see module
    docstring). One instance = one psycopg connection; each logical write
    commits immediately so status transitions reach Realtime subscribers
    as they happen, not at the end of the run."""

    def __init__(self, db_url: str | None = None) -> None:
        self.db_url = db_url or _default_db_url()
        self.conn: psycopg.Connection | None = None

    def connect(self) -> "SupabaseDataPlane":
        if self.conn is None:
            self.conn = psycopg.connect(self.db_url, row_factory=dict_row)
        return self

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            finally:
                self.conn = None

    def __enter__(self) -> "SupabaseDataPlane":
        return self.connect()

    def __exit__(self, *exc) -> None:
        self.close()

    # -- low-level helpers --------------------------------------------------

    def _one(self, sql: str, params: dict | tuple = ()) -> dict | None:
        assert self.conn is not None, "call connect() first"
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def _all(self, sql: str, params: dict | tuple = ()) -> list[dict]:
        assert self.conn is not None, "call connect() first"
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _exec(self, sql: str, params: dict | tuple = (), *, commit: bool = True) -> None:
        assert self.conn is not None, "call connect() first"
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
        if commit:
            self.conn.commit()

    # -- identity & tenancy ---------------------------------------------------

    def resolve_user(self, user: str) -> dict:
        """auth.users lookup by id (uuid) or email. Confirmed-email status
        rides along: analysis is refused for unconfirmed accounts."""
        uid = _as_uuid(user)
        if uid:
            row = self._one(
                "select id::text, email, "
                "  coalesce(email_confirmed_at, phone_confirmed_at) is not null as confirmed "
                "from auth.users where id = %s", (uid,))
        else:
            row = self._one(
                "select id::text, email, "
                "  coalesce(email_confirmed_at, phone_confirmed_at) is not null as confirmed "
                "from auth.users where lower(email) = lower(%s)", (user,))
        if row is None:
            raise NotProvisionedError(f"no auth.users row for {user!r}")
        return row

    def resolve_org(self, user_id: str, org: str | None = None) -> tuple[str, str]:
        """(org_id, role) for this user. When ``org`` is passed it is only a
        SELECTOR among the user's own memberships — membership is verified
        here regardless of what the caller claims (playbook: never trust a
        client-supplied org_id)."""
        memberships = self._all(
            "select m.org_id::text, m.role, o.name "
            "from public.memberships m join public.orgs o on o.id = m.org_id "
            "where m.user_id = %s order by o.created_at", (user_id,))
        if not memberships:
            raise NotProvisionedError(
                f"user {user_id} has no org membership - create one via "
                "app.create_org(name) first")
        if org is not None:
            oid = _as_uuid(org)
            for m in memberships:
                if m["org_id"] == oid:
                    return m["org_id"], m["role"]
            raise PermissionDeniedError(
                f"user {user_id} is not a member of org {org}")
        if len(memberships) > 1:
            raise MultipleOrgsError(memberships)
        return memberships[0]["org_id"], memberships[0]["role"]

    @staticmethod
    def require_role(role: str, minimum: str) -> None:
        if ROLE_RANK.get(role, -1) < ROLE_RANK[minimum]:
            raise PermissionDeniedError(
                f"role {role!r} is below the required {minimum!r}")

    # -- entitlements & quota -------------------------------------------------

    def get_entitlements(self, org_id: str) -> Entitlements:
        """Tier + plan for an org, resolved in the DB (``app.org_tier`` over
        the subscriptions row, defaulting to free). THE source of truth the
        engine runs on."""
        row = self._one(
            "select e.* from public.plan_entitlements e "
            "where e.tier = app.org_tier(%(org)s)", {"org": org_id})
        if row is None:
            raise SaasError(
                f"app.org_tier({org_id}) resolved to a tier missing from "
                "plan_entitlements - re-apply supabase/migrations/0004")
        tier = normalize_tier(row["tier"])
        frameworks = row["frameworks"]
        if isinstance(frameworks, str):     # jsonb '"all"' arrives as str
            frameworks = frameworks.strip('"')
        return Entitlements(
            org_id=org_id, tier=tier,
            llm_provider=row["llm_provider"], llm_model=row["llm_model"],
            max_output_tokens=row["max_output_tokens"],
            scans_per_month=row["scans_per_month"], seats=row["seats"],
            api_access=row["api_access"], sso=row["sso"], sla=row["sla"],
            frameworks=frameworks, drift=_entitlement_drift(tier, row))

    def check_quota(self, org_id: str) -> dict:
        row = self._one("select app.check_quota(%s) as q", (org_id,))
        return row["q"] if row else {}

    def consume_quota(self, org_id: str, run_id: str | None = None) -> dict:
        """DEPRECATED (0008): superseded by consume_credits — kept one release
        for rollback, mirroring app.consume_scan_quota's own deprecation."""
        assert self.conn is not None
        with self.conn.cursor() as cur:
            cur.execute("select app.consume_scan_quota(%s, %s) as d",
                        (org_id, run_id))
            decision = cur.fetchone()["d"]
        self.conn.commit()
        if not decision.get("allowed"):
            raise QuotaExceededError(decision.get("used", 0), decision.get("limit"))
        return decision

    # -- credits (migration 0008 — the usage currency) ------------------------

    def credit_cost(self, org_id: str, kind: str, cards: int = 1) -> int:
        """Published flat price of one run for this org's CURRENT tier —
        known before execution (app.credit_cost over credit_costs)."""
        row = self._one("select app.credit_cost(%s, %s, %s) as c",
                        (org_id, kind, cards))
        return int(row["c"])

    def ensure_cycle_grant(self, org_id: str) -> dict:
        """Grant the current allowance cycle if not yet granted (idempotent
        by cycle key — safe to call before every consume)."""
        assert self.conn is not None
        with self.conn.cursor() as cur:
            cur.execute("select app.ensure_cycle_grant(%s) as g", (org_id,))
            grant = cur.fetchone()["g"]
        self.conn.commit()
        return grant

    def consume_credits(self, org_id: str, run_id: str | None, cost: int) -> dict:
        """Atomic consume-or-reject BEFORE expensive work (SELECT ... FOR
        UPDATE on the org's credit_balances row — parallel submissions can
        never overspend). The §8.5 sibling of consume_quota."""
        assert self.conn is not None
        with self.conn.cursor() as cur:
            cur.execute("select app.consume_credits(%s, %s, %s) as d",
                        (org_id, run_id, cost))
            decision = cur.fetchone()["d"]
        self.conn.commit()
        if not decision.get("allowed"):
            raise InsufficientCreditsError(
                decision.get("needed", cost), decision.get("balance", 0))
        return decision

    def credit_balance(self, org_id: str) -> dict:
        row = self._one("select app.credit_balance(%s) as b", (org_id,))
        return row["b"] if row else {}

    def refund_credits(self, org_id: str, run_id: str) -> dict:
        """System-failure refund (DLQ / llm_error / infra) — ledger-derived
        amount, idempotent under double-fire."""
        assert self.conn is not None
        with self.conn.cursor() as cur:
            cur.execute("select app.refund_credits(%s, %s) as r",
                        (org_id, run_id))
            refund = cur.fetchone()["r"]
        self.conn.commit()
        return refund

    def settle_run_tokens(self, org_id: str, run_id: str,
                          in_tok: int, out_tok: int) -> dict:
        """DEPRECATED (0012) — post-run token settlement (0011): the LLM
        component of the price, charged from actual usage at the tier's
        published token_rates. Idempotent per run; clamps to the available
        balance, forgiving any shortfall.

        That clamp is exactly the overspend hole 0012 closes. This stays only
        as the fallback for runs enqueued before 0012 deployed, which have no
        hold to settle. New runs go through settle_hold."""
        assert self.conn is not None
        with self.conn.cursor() as cur:
            cur.execute("select app.settle_run_tokens(%s, %s, %s, %s) as s",
                        (org_id, run_id, in_tok, out_tok))
            settlement = cur.fetchone()["s"]
        self.conn.commit()
        return settlement

    # -- metered credits (migration 0012 — reserve → meter → settle) ---------

    def reserve_credits(self, org_id: str, run_id: str, floor_credits: int,
                        forecast: int = 0) -> dict:
        """Escrow floor + forecast BEFORE the run. Raises the same
        InsufficientCreditsError as consume_credits on rejection, so callers
        that already handle the 402 contract need no change."""
        assert self.conn is not None
        with self.conn.cursor() as cur:
            cur.execute("select app.reserve_credits(%s, %s, %s, %s) as d",
                        (org_id, run_id, floor_credits, forecast))
            decision = cur.fetchone()["d"]
        self.conn.commit()
        if not decision.get("allowed"):
            raise InsufficientCreditsError(
                decision.get("needed", floor_credits), decision.get("balance", 0))
        return decision

    def meter_effort(self, org_id: str, run_id: str, unit: str,
                     qty: float, meta: dict | None = None) -> dict:
        """Charge one unit of engine effort against the run's hold, as it
        happens. Returns live headroom; ``exhausted`` is the engine's signal
        to stop starting new work.

        Commits immediately and per event — the deduction must be visible to
        the user's live feed and to a concurrently-reading balance query while
        the run is still going. That is the whole point of metering in real
        time rather than settling at the end."""
        assert self.conn is not None
        with self.conn.cursor() as cur:
            cur.execute("select app.meter_effort(%s, %s, %s, %s, %s) as m",
                        (org_id, run_id, unit, qty, Jsonb(meta or {})))
            reading = cur.fetchone()["m"]
        self.conn.commit()
        return reading

    def settle_hold(self, org_id: str, run_id: str) -> dict:
        """Finalise: charge max(floor, ceil(metered)) capped at the reserve,
        return the remainder. Idempotent. Returns {'settled': False,
        'reason': 'no_hold'} for pre-0012 runs so the caller can fall back."""
        assert self.conn is not None
        with self.conn.cursor() as cur:
            cur.execute("select app.settle_hold(%s, %s) as s", (org_id, run_id))
            settlement = cur.fetchone()["s"]
        self.conn.commit()
        return settlement

    def reset_hold_meter(self, org_id: str, run_id: str) -> dict:
        """Zero a requeued run's meter so a retry does not bill the dead
        attempt's tokens. The effort stays recorded as absorbed cost."""
        assert self.conn is not None
        with self.conn.cursor() as cur:
            cur.execute("select app.reset_hold_meter(%s, %s) as r",
                        (org_id, run_id))
            reset = cur.fetchone()["r"]
        self.conn.commit()
        return reset

    def release_hold(self, org_id: str, run_id: str, keep: int = 0) -> dict:
        """Failure path: return the escrow, keeping ``keep`` credits for
        effort genuinely delivered. Idempotent."""
        assert self.conn is not None
        with self.conn.cursor() as cur:
            cur.execute("select app.release_hold(%s, %s, %s) as r",
                        (org_id, run_id, keep))
            release = cur.fetchone()["r"]
        self.conn.commit()
        return release

    def provider_cost_cents(self, model: str | None, in_tok: int,
                            out_tok: int) -> int | None:
        """True provider spend for this run, in USD cents. None for an unknown
        model — never 0, which would read as 100% margin on the dashboard."""
        if not model:
            return None
        row = self._one("select app.provider_cost_cents(%s, %s, %s) as c",
                        (model, in_tok, out_tok))
        return None if row is None or row["c"] is None else int(row["c"])

    # -- audit ------------------------------------------------------------

    def audit(self, org_id: str | None, actor: str | None, action: str,
              target: str | None = None, meta: dict | None = None) -> None:
        """Hash-chained, append-only audit event (app.log_audit_event).
        Never put secrets or raw PII in meta."""
        self._exec("select app.log_audit_event(%s, %s, %s, %s, %s)",
                   (org_id, actor, action, target, Jsonb(meta or {})))

    # -- pipeline rows ------------------------------------------------------

    def create_submission(self, org_id: str, user_id: str,
                          title: str | None) -> str:
        row = self._one(
            "insert into public.submissions (org_id, created_by, title) "
            "values (%s, %s, %s) returning id::text", (org_id, user_id, title))
        self.conn.commit()
        return row["id"]

    def register_asset(self, submission_id: str, org_id: str, kind: str,
                       checksum: str | None = None,
                       source_url: str | None = None) -> str:
        row = self._one(
            "insert into public.assets (submission_id, org_id, kind, checksum, "
            "  source_url, scan_status) "
            "values (%s, %s, %s, %s, %s, 'clean') returning id::text",
            (submission_id, org_id, kind, checksum, source_url))
        self.conn.commit()
        return row["id"]

    def create_run(self, submission_id: str, org_id: str, tier: str,
                   model_id: str, resumed_from: str | None = None) -> str:
        row = self._one(
            "insert into public.analysis_runs (submission_id, org_id, status, "
            "  tier, model_id, resumed_from_run_id) "
            "values (%s, %s, 'queued', %s, %s, %s) returning id::text",
            (submission_id, org_id, tier, model_id, resumed_from))
        self.conn.commit()
        return row["id"]

    _RUN_FIELDS = ("status", "error", "model_id", "prompt_version",
                   "rulepack_version", "rag_corpus_hash", "input_tokens",
                   "output_tokens", "cost_cents", "engine_run_id")

    def set_run(self, run_id: str, *, started: bool = False,
                finished: bool = False, **fields: Any) -> None:
        unknown = set(fields) - set(self._RUN_FIELDS)
        if unknown:
            raise ValueError(f"not analysis_runs columns: {sorted(unknown)}")
        sets = [f"{k} = %({k})s" for k in fields]
        if started:
            sets.append("started_at = coalesce(started_at, now())")
        if finished:
            sets.append("finished_at = now()")
        if not sets:
            return
        fields["run_id"] = run_id
        self._exec(
            f"update public.analysis_runs set {', '.join(sets)} "
            "where id = %(run_id)s", fields)

    def save_layer_output(self, run_id: str, org_id: str, layer: str,
                          payload: dict) -> None:
        self._exec(
            "insert into public.layer_outputs (run_id, org_id, layer, payload) "
            "values (%s, %s, %s, %s) "
            "on conflict (run_id, layer) do update set payload = excluded.payload",
            (run_id, org_id, layer, Jsonb(payload)))

    def emit_run_event(self, run_id: str, org_id: str, stage: str,
                       event: str, message: str,
                       detail: dict | None = None) -> None:
        """One sanitized live-activity line (public.run_events, 0011). The
        user watches these while the engine runs: fixed message templates
        plus aggregate counts ONLY — never ad text, retrieved regulation
        chunks, prompts, or model reasoning. Never raises: the feed is
        best-effort and must not take a run down with it."""
        try:
            self._exec(
                "insert into public.run_events "
                "  (run_id, org_id, stage, event, message, detail) "
                "values (%s, %s, %s, %s, %s, %s)",
                (run_id, org_id, stage, event, message, Jsonb(detail or {})))
        except Exception:  # noqa: BLE001
            logger.warning("run_events insert failed for %s/%s", run_id, event)
            try:
                self.conn.rollback()   # keep the shared connection usable
            except Exception:  # noqa: BLE001
                pass

    def load_asset_representation(self, run_id: str) -> dict:
        """The stored Layer-1/2 output — lets an operator resume a
        human_review run without re-OCRing the creative."""
        row = self._one(
            "select payload from public.layer_outputs "
            "where run_id = %s and layer = 'nlp'", (run_id,))
        if row is None:
            raise SaasError(f"run {run_id} has no stored nlp layer output")
        return row["payload"]

    _RUN_COLS = ("id::text, org_id::text, submission_id::text, status, tier, "
                 "model_id, engine_run_id, resumed_from_run_id::text, error")

    def find_run(self, ref: str) -> dict:
        """analysis_runs row by DB uuid or by engine_run_id ('run_<hex>')."""
        rid = _as_uuid(ref)
        row = (self._one(f"select {self._RUN_COLS} "
                         "from public.analysis_runs where id = %s", (rid,))
               if rid else
               self._one(f"select {self._RUN_COLS} "
                         "from public.analysis_runs where engine_run_id = %s "
                         "order by created_at desc limit 1", (ref,)))
        if row is None:
            raise SaasError(f"no analysis_runs row for {ref!r}")
        return row

    # -- findings ------------------------------------------------------------

    @staticmethod
    def _clamp_severity(value: Any) -> str:
        v = str(value or "").lower()
        return v if v in _VALID_SEVERITIES else "medium"

    @staticmethod
    def _clamp_verdict(value: Any) -> str:
        v = str(value or "").lower()
        return v if v in _VALID_VERDICTS else "needs_review"

    def save_findings(self, run_id: str, org_id: str,
                      llm_review: dict | None,
                      verification: dict | None) -> int:
        """Persist the run's outcome as reviewable ``findings`` rows.

        Two sources: the final LLM review document (verdicts as the model
        wrote them — the check constraint matches its vocabulary), and the
        rule engine's asset defects (deterministic true statements about
        the creative, recorded as potential violations with the check id
        as rule_ref). Advisories stay in layer_outputs only — they are
        informational and never gate anything."""
        rows: list[tuple] = []
        for f in (llm_review or {}).get("findings", []):
            citations = [str(c) for c in f.get("regulation_citations") or []]
            rows.append((
                run_id, org_id,
                str(f.get("framework") or "UNKNOWN"),
                "; ".join(citations) or None,
                self._clamp_severity(f.get("severity")),
                self._clamp_verdict(f.get("verdict")),
                Jsonb({"source": "llm_review",
                       "finding_id": f.get("finding_id"),
                       "cited_segment_ids": f.get("cited_segment_ids") or [],
                       "cited_entity_ids": f.get("cited_entity_ids") or [],
                       "claim_candidate_id": f.get("claim_candidate_id"),
                       "quoted_evidence": f.get("quoted_evidence")}),
                f.get("reasoning") or f.get("quoted_evidence") or "(no reasoning)",
                f.get("scope_of_improvement"),
            ))
        for d in (verification or {}).get("asset_defects", []):
            rows.append((
                run_id, org_id,
                "RULE_ENGINE",
                d.get("check_id"),
                self._clamp_severity(d.get("severity")),
                "potential_violation",
                Jsonb({"source": "rule_engine_asset_defect",
                       "evidence": d.get("evidence") or {}}),
                d.get("message") or "(no message)",
                None,
            ))
        if not rows:
            return 0
        assert self.conn is not None
        with self.conn.cursor() as cur:
            cur.executemany(
                "insert into public.findings (run_id, org_id, framework, rule_ref, "
                "  severity, verdict, location, message, remediation) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s)", rows)
        self.conn.commit()
        return len(rows)

    # -- metering ------------------------------------------------------------

    def record_token_usage(self, org_id: str, run_id: str, user_id: str | None,
                           model: str | None, input_tokens: int | None,
                           output_tokens: int | None, tier: str) -> None:
        self._exec(
            "insert into public.usage_events (org_id, run_id, user_id, kind, "
            "  model, input_tokens, output_tokens, meta) "
            "values (%s, %s, %s, 'token_spend', %s, %s, %s, %s)",
            (org_id, run_id, user_id, model, input_tokens, output_tokens,
             Jsonb({"tier": tier})))

    # -- API keys (Pro+ programmatic access) ----------------------------------

    def issue_api_key(self, org_id: str, created_by: str, name: str,
                      scopes: list[str] | None = None) -> str:
        """Mint ``ack_<hex>`` for an org. The PLAINTEXT is returned exactly
        once and never stored — only its sha256 lands in api_keys. Requires
        the org's plan to include api_access."""
        ent = self.get_entitlements(org_id)
        if not ent.api_access:
            raise PermissionDeniedError(
                f"tier {ent.tier!r} does not include API access")
        plaintext = "ack_" + secrets.token_hex(24)
        key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        self._exec(
            "insert into public.api_keys (org_id, name, key_hash, scopes, created_by) "
            "values (%s, %s, %s, %s, %s)",
            (org_id, name, key_hash, scopes or ["submit", "read"], created_by))
        self.audit(org_id, created_by, "api_key.created", f"api_key:{name}",
                   {"scopes": scopes or ["submit", "read"]})
        return plaintext

    def verify_api_key(self, plaintext: str, *, scope: str | None = None) -> dict:
        """Resolve a presented key to (org_id, scopes) or raise. Checks, in
        order: hash exists, not revoked, org still entitled to API access,
        requested scope granted. Bumps last_used_at."""
        key_hash = hashlib.sha256((plaintext or "").encode()).hexdigest()
        row = self._one(
            "select id::text, org_id::text, scopes, revoked_at "
            "from public.api_keys where key_hash = %s", (key_hash,))
        if row is None:
            raise ApiKeyError("unknown API key")
        if row["revoked_at"] is not None:
            raise ApiKeyError("API key is revoked")
        ent = self.get_entitlements(row["org_id"])
        if not ent.api_access:
            raise ApiKeyError(
                f"org tier {ent.tier!r} no longer includes API access")
        if scope is not None and scope not in (row["scopes"] or []):
            raise ApiKeyError(f"API key lacks the {scope!r} scope")
        self._exec("update public.api_keys set last_used_at = now() where id = %s",
                   (row["id"],))
        return {"org_id": row["org_id"], "scopes": row["scopes"], "key_id": row["id"]}


# ---------------------------------------------------------------------------
# Framework entitlement scoping (Layer 2 -> 3 seam).

def _apply_framework_entitlements(asset: dict, ent: Entitlements) -> list[str]:
    """Trim routed frameworks to the plan's list; returns what was dropped.

    Deterministic checks are registered per framework, so removing one from
    routing removes its rule checks too — no orphaned rule can demand review
    content the tier filtered away. If the filter would empty routing
    entirely the original routing is kept (a compliance review that silently
    reviews nothing is worse than over-serving one framework) and the bypass
    is flagged for the operator via the returned sentinel."""
    if ent.frameworks == "all" or not isinstance(ent.frameworks, list):
        return []
    routing = asset.get("routing") or {}
    routed = list(routing.get("frameworks") or [])
    allowed = {str(f).upper() for f in ent.frameworks}
    kept = [f for f in routed if str(f).upper() in allowed]
    dropped = [f for f in routed if str(f).upper() not in allowed]
    if routed and not kept:
        return ["__bypass__"] + dropped
    routing["frameworks"] = kept
    asset["routing"] = routing
    return dropped


# ---------------------------------------------------------------------------
# The tenant-scoped engine run.

def _sha256_of_input(image_path, text, html) -> tuple[str, str | None]:
    """(assets.kind, checksum) for the submitted creative."""
    if sum(v is not None for v in (image_path, text, html)) != 1:
        raise ValueError("provide exactly one of image_path, text, or html")
    if text is not None:
        return "text", hashlib.sha256(text.encode("utf-8")).hexdigest()
    if html is not None:
        return "html", hashlib.sha256(html.encode("utf-8")).hexdigest()
    paths = image_path if isinstance(image_path, list) else [image_path]
    h = hashlib.sha256()
    for p in paths:
        with open(p, "rb") as fh:
            h.update(fh.read())
    return "image", h.hexdigest()


def _persist_outcome(db: SupabaseDataPlane, *, run_id: str, org_id: str,
                     user_id: str, ent: Entitlements,
                     result: EngineRunResult) -> None:
    """Layers 3+4 outputs, findings, token metering, final status + audit."""
    dump = result.model_dump(mode="json")
    db.set_run(run_id, status="reconciling")
    db.save_layer_output(run_id, org_id, "llm", {
        "llm_review": dump["llm_review"],
        "rounds": dump["rounds"],
        "llm_rounds_used": dump["llm_rounds_used"],
        "max_llm_rounds": dump["max_llm_rounds"],
    })
    db.save_layer_output(run_id, org_id, "rule", {
        "verification": dump["verification"],
        "human_review": dump["human_review"],
        "engine_status": dump["status"],
        "warnings": dump["warnings"],
    })
    n_findings = db.save_findings(run_id, org_id, result.llm_review,
                                  dump["verification"])

    meta = (result.llm_review or {}).get("llm_meta", {})
    # Bill on the SUM across all LLM rounds (a 3-round run consumed 3 calls);
    # fall back to the final round's meta when per-round usage is absent.
    total_in = total_out = 0
    for r in dump["rounds"] or []:
        rmeta = (r.get("llm_review") or {}).get("llm_meta") or {}
        total_in += int(rmeta.get("input_tokens") or 0)
        total_out += int(rmeta.get("output_tokens") or 0)
    if total_in == 0 and total_out == 0:
        total_in = int(meta.get("input_tokens") or 0)
        total_out = int(meta.get("output_tokens") or 0)
    db.record_token_usage(org_id, run_id, user_id, meta.get("model"),
                          total_in or None, total_out or None, ent.tier)

    model_used = meta.get("model") or ent.llm_model

    # Settlement (0012): charge max(floor, ceil(metered)) against the run's
    # hold, capped at what was reserved, and return the remainder. Tokens were
    # already metered round-by-round inside the engine, so this only finalises.
    #
    # A run enqueued before 0012 deployed has no hold — settle_hold says so and
    # we fall back to the 0011 token settlement for it. That fallback goes away
    # with the deprecation of settle_run_tokens one release from now.
    settlement = db.settle_hold(org_id, run_id)
    if not settlement.get("settled") and settlement.get("reason") == "no_hold":
        settlement = db.settle_run_tokens(org_id, run_id, total_in, total_out)

    db_status = _RUN_STATUS_BY_ENGINE_STATUS[result.status]
    db.set_run(
        run_id, finished=True, status=db_status,
        error=result.llm_error,
        engine_run_id=result.run_id,
        model_id=model_used,
        prompt_version=result.provenance.get("prompt_version"),
        rulepack_version=result.provenance.get("ruleset_version"),
        rag_corpus_hash=result.provenance.get("rag_corpus_hash"),
        input_tokens=total_in or None, output_tokens=total_out or None,
        # True provider spend — the denominator of every margin number. The
        # column has existed since 0001 and been null ever since; without it
        # the tier rates are unfalsifiable.
        cost_cents=db.provider_cost_cents(model_used, total_in, total_out))

    action = {"complete": "run.completed", "failed": "run.failed",
              "human_review": "run.human_review"}[db_status]
    db.audit(org_id, user_id, action, f"analysis_run:{run_id}", {
        "engine_run_id": result.run_id, "tier": ent.tier,
        "llm_rounds_used": result.llm_rounds_used, "findings": n_findings,
        "review_passed": bool(result.verification
                              and result.verification.review_passed),
        "tokens": {"input": total_in, "output": total_out},
        "settlement": settlement,
    })

    charged = int((settlement or {}).get("charged") or 0)
    returned = int((settlement or {}).get("returned") or 0)
    db.emit_run_event(
        run_id, org_id, "report", "report.persisted",
        f"Report compiled — {n_findings} finding"
        f"{'s' if n_findings != 1 else ''} recorded.",
        {"findings": n_findings, "status": db_status})
    db.emit_run_event(
        run_id, org_id, "done", "run.finished",
        ("Review complete." if db_status == "complete" else
         "Review paused for human review — a compliance reviewer should "
         "add guidance." if db_status == "human_review" else
         "The run failed; any charge is refunded automatically.")
        + (f" Charged {charged} credit{'s' if charged != 1 else ''} for "
           f"{(total_in + total_out):,} tokens of model work."
           if charged else "")
        + (f" {returned} unused credit{'s' if returned != 1 else ''} "
           "returned to your balance." if returned else ""),
        {"status": db_status, "credits_charged": charged,
         "credits_returned": returned,
         "input_tokens": total_in, "output_tokens": total_out})


def run_for_user(
    *,
    user: str,
    org: str | None = None,
    asset_id: str | None = None,
    image_path: str | list[str] | None = None,
    text: str | None = None,
    html: str | None = None,
    title: str | None = None,
    target_jurisdictions: list[str] | None = None,
    as_of: date | None = None,
    max_llm_rounds: int = DEFAULT_MAX_LLM_ROUNDS,
    cost: int | None = None,
    conn: Any = None,
    embedder: Any = None,
    retriever: Any = None,
    provider: Any = None,
    include_asset: bool = False,
    db: SupabaseDataPlane | None = None,
) -> EngineRunResult:
    """The whole engine for one tenant: tier fetched from Supabase, credits
    consumed first, every layer persisted, everything audited.

    ``user`` is an auth.users id or email; ``org`` is only needed when the
    user belongs to several orgs. ``cost`` is the pre-computed credit price
    from the API layer (§8.5); when None it is computed here from the
    published price list (app.credit_cost) so direct/CLI callers keep
    working. ``conn``/``embedder``/``retriever``/``provider`` are the usual
    test-injection seams and do not weaken any tenancy gate. Raises
    NotProvisionedError / PermissionDeniedError / MultipleOrgsError /
    InsufficientCreditsError (a QuotaExceededError) before any layer runs.
    """
    own_db = db is None
    if own_db:
        db = SupabaseDataPlane().connect()
    try:
        # -- identity, tenancy, entitlements (all DB-resolved) -------------
        user_row = db.resolve_user(user)
        user_id = user_row["id"]
        org_id, role = db.resolve_org(user_id, org)
        db.require_role(role, SUBMIT_MIN_ROLE)
        if not user_row["confirmed"]:
            raise PermissionDeniedError(
                f"account {user_row['email']} has not confirmed its email - "
                "analysis features require a verified account")

        ent = db.get_entitlements(org_id)
        if ent.drift:
            logger.warning("entitlement drift for org %s: %s", org_id, ent.drift)
            db.audit(org_id, user_id, "entitlements.drift", f"tier:{ent.tier}",
                     {"drift": ent.drift})

        # -- pipeline rows, then the credit gate BEFORE any expensive layer --
        kind, checksum = _sha256_of_input(image_path, text, html)
        cards = len(image_path) if isinstance(image_path, list) else 1
        submission_id = db.create_submission(org_id, user_id, title)
        asset_row_id = db.register_asset(submission_id, org_id, kind, checksum)
        run_id = db.create_run(submission_id, org_id, ent.tier, ent.llm_model)
        db.audit(org_id, user_id, "submission.created",
                 f"submission:{submission_id}",
                 {"kind": kind, "checksum": checksum, "title": title})
        try:
            db.ensure_cycle_grant(org_id)
            run_cost = cost if cost is not None else db.credit_cost(
                org_id, "carousel" if kind == "image" and cards > 1 else kind,
                cards)
            quota = db.consume_credits(org_id, run_id, run_cost)
        except QuotaExceededError as exc:
            db.set_run(run_id, finished=True, status="failed",
                       error=f"rejected: {exc}")
            db.audit(org_id, user_id, "run.quota_rejected",
                     f"analysis_run:{run_id}",
                     {"needed": getattr(exc, "needed", None),
                      "balance": getattr(exc, "balance", None),
                      "tier": ent.tier})
            raise

        try:
            # -- layers 1+2 (OCR tier follows the DB tier) ------------------
            db.set_run(run_id, status="running_cv", started=True)
            db.audit(org_id, user_id, "run.started", f"analysis_run:{run_id}",
                     {"tier": ent.tier, "model": ent.llm_model,
                      "credits_charged": quota.get("charged"),
                      "sub_bal": quota.get("sub_bal"),
                      "pack_bal": quota.get("pack_bal")})
            asset = prepare_asset(
                asset_id=asset_id, image_path=image_path, text=text, html=html,
                product_tier=ent.tier,
                target_jurisdictions=target_jurisdictions)
            db.set_run(run_id, status="running_nlp")
            dropped = _apply_framework_entitlements(asset, ent)
            bypassed = dropped[:1] == ["__bypass__"]
            db.save_layer_output(run_id, org_id, "cv", {
                "provenance": asset.get("provenance", {}),
                "segments": len(asset.get("segments", [])),
            })
            db.save_layer_output(run_id, org_id, "nlp", asset)

            # -- layers 3+4 (tier = the DB tier, end to end) ----------------
            db.set_run(run_id, status="running_llm")
            result = review_and_verify(
                asset, ent.tier,
                max_llm_rounds=max_llm_rounds, as_of=as_of,
                conn=conn, embedder=embedder, retriever=retriever,
                provider=provider, include_asset=include_asset)
        except Exception as exc:
            db.set_run(run_id, finished=True, status="failed",
                       error=f"{type(exc).__name__}: {exc}"[:2000])
            db.audit(org_id, user_id, "run.failed", f"analysis_run:{run_id}",
                     {"error": str(exc)[:500]})
            raise

        if bypassed:
            result.warnings.append(
                "framework entitlement filter would have removed EVERY routed "
                f"framework ({dropped[1:]}) - routing kept as-is; review this "
                f"org's plan ({ent.tier})")
        elif dropped:
            result.warnings.append(
                f"frameworks outside the {ent.tier} plan were not reviewed: "
                + ", ".join(dropped))
        result.provenance["saas"] = {
            "org_id": org_id, "submission_id": submission_id,
            "asset_row_id": asset_row_id, "analysis_run_id": run_id,
            "tier_source": "supabase:app.org_tier",
            "frameworks_dropped_by_plan": [] if bypassed else dropped,
            "quota_after_consume": quota,
        }
        _persist_outcome(db, run_id=run_id, org_id=org_id, user_id=user_id,
                         ent=ent, result=result)
        return result
    finally:
        if own_db:
            db.close()


def resume_run(
    *,
    user: str,
    run: str,
    guidance: str,
    as_of: date | None = None,
    conn: Any = None,
    embedder: Any = None,
    retriever: Any = None,
    provider: Any = None,
    include_asset: bool = False,
    db: SupabaseDataPlane | None = None,
) -> EngineRunResult:
    """Operator interference over a persisted run: one more LLM round with
    the operator's direction, as a NEW analysis_runs row linked via
    resumed_from_run_id. No new scan quota is consumed — it is the same
    creative — but the extra token spend is metered. The stored Layer-1/2
    output is reused (no re-OCR); the tier is re-fetched, so a plan change
    between run and resume takes effect immediately."""
    own_db = db is None
    if own_db:
        db = SupabaseDataPlane().connect()
    try:
        user_row = db.resolve_user(user)
        user_id = user_row["id"]
        prev = db.find_run(run)
        org_id, role = db.resolve_org(user_id, prev["org_id"])
        db.require_role(role, SUBMIT_MIN_ROLE)

        ent = db.get_entitlements(org_id)
        asset = db.load_asset_representation(prev["id"])
        run_id = db.create_run(prev["submission_id"], org_id, ent.tier,
                               ent.llm_model, resumed_from=prev["id"])
        db.set_run(run_id, status="running_llm", started=True)
        db.audit(org_id, user_id, "run.resumed", f"analysis_run:{run_id}",
                 {"resumed_from": prev["id"], "tier": ent.tier,
                  "guidance_chars": len(guidance)})
        try:
            result = resume_with_human_guidance(
                asset, guidance, product_tier=ent.tier, as_of=as_of,
                conn=conn, embedder=embedder, retriever=retriever,
                provider=provider, include_asset=include_asset)
        except Exception as exc:
            db.set_run(run_id, finished=True, status="failed",
                       error=f"{type(exc).__name__}: {exc}"[:2000])
            db.audit(org_id, user_id, "run.failed", f"analysis_run:{run_id}",
                     {"error": str(exc)[:500], "resumed_from": prev["id"]})
            raise
        db.save_layer_output(run_id, org_id, "nlp", asset)
        result.provenance["saas"] = {
            "org_id": org_id, "submission_id": prev["submission_id"],
            "analysis_run_id": run_id, "resumed_from_run_id": prev["id"],
            "tier_source": "supabase:app.org_tier",
        }
        _persist_outcome(db, run_id=run_id, org_id=org_id, user_id=user_id,
                         ent=ent, result=result)
        return result
    finally:
        if own_db:
            db.close()


__all__ = [
    "ApiKeyError", "Entitlements", "InsufficientCreditsError",
    "MultipleOrgsError", "NotProvisionedError", "PermissionDeniedError",
    "QuotaExceededError", "SaasError", "SupabaseDataPlane", "resume_run",
    "run_for_user",
]

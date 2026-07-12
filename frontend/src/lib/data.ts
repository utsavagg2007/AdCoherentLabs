import { cache } from "react";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { isDemoMode } from "@/lib/env";
import { ENTITLEMENTS, TIERS } from "@/lib/entitlements";
import type {
  AnalysisRun,
  ApiKey,
  Asset,
  AssetKind,
  Finding,
  LayerOutput,
  OrgSummary,
  PlanEntitlement,
  Quota,
  Role,
  RunStatus,
  SessionContext,
  Severity,
  Submission,
  Tier,
  UsageEvent,
} from "@/lib/types";
import * as demo from "@/lib/demo/fixtures";

export const ACTIVE_ORG_COOKIE = "ac-org";

export type SessionState =
  | { kind: "unauthenticated" }
  | { kind: "no-org"; user: { id: string; email: string } }
  | { kind: "ready"; ctx: SessionContext };

// ── Session / org context ────────────────────────────────────────────────────

export const getSessionState = cache(async (): Promise<SessionState> => {
  if (isDemoMode) return { kind: "ready", ctx: demo.DEMO_SESSION };

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return { kind: "unauthenticated" };

  const { data: memberships } = await supabase
    .from("memberships")
    .select("org_id, role, orgs(id, name)")
    .order("created_at", { ascending: true });

  const orgs: OrgSummary[] = (memberships ?? [])
    .map((m) => {
      const org = m.orgs as unknown as { id: string; name: string } | null;
      return org ? { id: org.id, name: org.name, role: m.role as Role } : null;
    })
    .filter((o): o is OrgSummary => o !== null);

  const userInfo = { id: user.id, email: user.email ?? "" };
  if (orgs.length === 0) return { kind: "no-org", user: userInfo };

  const cookieStore = await cookies();
  const preferred = cookieStore.get(ACTIVE_ORG_COOKIE)?.value;
  const org = orgs.find((o) => o.id === preferred) ?? orgs[0];

  const [quota, subscription] = await Promise.all([
    computeQuota(org.id),
    supabase
      .from("subscriptions")
      .select("tier, status, current_period_end, stripe_customer_id")
      .eq("org_id", org.id)
      .maybeSingle()
      .then((r) => r.data),
  ]);

  return {
    kind: "ready",
    ctx: {
      user: userInfo,
      org,
      orgs,
      role: org.role,
      quota,
      subscription: subscription ?? {
        tier: "free",
        status: "active",
        current_period_end: null,
        stripe_customer_id: null,
      },
      demo: false,
    },
  };
});

/** For pages inside the app shell: redirects instead of returning null. */
export async function requireContext(): Promise<SessionContext> {
  const state = await getSessionState();
  if (state.kind === "unauthenticated") redirect("/login");
  if (state.kind === "no-org") redirect("/onboarding");
  return state.ctx;
}

/**
 * Quota computed from RLS-readable tables (subscriptions, plan_entitlements,
 * usage_events) so no RPC wrapper is required for reads. Mirrors
 * app.check_quota() in migration 0004.
 */
async function computeQuota(orgId: string): Promise<Quota> {
  const supabase = await createClient();

  const { data: sub } = await supabase
    .from("subscriptions")
    .select("tier, status, current_period_start, current_period_end")
    .eq("org_id", orgId)
    .maybeSingle();

  const activeIsh = ["trialing", "active", "past_due"];
  const tier: Tier =
    sub && activeIsh.includes(sub.status) ? (sub.tier as Tier) : "free";

  const { data: entRow } = await supabase
    .from("plan_entitlements")
    .select("*")
    .eq("tier", tier)
    .maybeSingle();
  const ent: PlanEntitlement =
    (entRow as PlanEntitlement | null) ?? ENTITLEMENTS[tier];

  const monthStart = new Date();
  monthStart.setUTCDate(1);
  monthStart.setUTCHours(0, 0, 0, 0);
  const periodStart = sub?.current_period_start ?? monthStart.toISOString();

  const { count } = await supabase
    .from("usage_events")
    .select("id", { count: "exact", head: true })
    .eq("org_id", orgId)
    .eq("kind", "scan")
    .gte("created_at", periodStart);

  const used = count ?? 0;
  const limit = ent.scans_per_month;
  return {
    tier,
    model: ent.llm_model,
    limit,
    used,
    remaining: limit == null ? null : Math.max(limit - used, 0),
    api_access: ent.api_access,
    period_end: sub?.current_period_end ?? null,
  };
}

// ── Dashboard ────────────────────────────────────────────────────────────────

export interface RunListItem extends AnalysisRun {
  submissionTitle: string;
  findingsCount: number;
}

export interface DashboardData {
  submissionsCount: number;
  activeRuns: number;
  openBySeverity: Record<Severity, number>;
  complianceRate: number | null; // share of recent findings judged compliant
  recentRuns: RunListItem[];
  recentFindings: Finding[];
}

export async function getDashboardData(orgId: string): Promise<DashboardData> {
  if (isDemoMode) {
    const open = demo.DEMO_FINDINGS.filter((f) => f.status === "open");
    return {
      submissionsCount: demo.DEMO_SUBMISSIONS.length,
      activeRuns: demo.DEMO_RUNS.filter(
        (r) => r.status !== "complete" && r.status !== "failed",
      ).length,
      openBySeverity: countBySeverity(open),
      complianceRate: rate(demo.DEMO_FINDINGS),
      recentRuns: demoRunList(),
      recentFindings: open.slice(0, 4),
    };
  }

  const supabase = await createClient();
  const [subCount, activeRuns, findings, runs] = await Promise.all([
    supabase
      .from("submissions")
      .select("id", { count: "exact", head: true })
      .eq("org_id", orgId),
    supabase
      .from("analysis_runs")
      .select("id", { count: "exact", head: true })
      .eq("org_id", orgId)
      .not("status", "in", "(complete,failed)"),
    supabase
      .from("findings")
      .select("*")
      .eq("org_id", orgId)
      .order("created_at", { ascending: false })
      .limit(200),
    supabase
      .from("analysis_runs")
      .select("*, submissions(title), findings(count)")
      .eq("org_id", orgId)
      .order("created_at", { ascending: false })
      .limit(8),
  ]);

  const allFindings = (findings.data ?? []) as Finding[];
  const open = allFindings.filter((f) => f.status === "open");

  return {
    submissionsCount: subCount.count ?? 0,
    activeRuns: activeRuns.count ?? 0,
    openBySeverity: countBySeverity(open),
    complianceRate: rate(allFindings),
    recentRuns: mapRunRows(runs.data ?? []),
    recentFindings: open.slice(0, 4),
  };
}

function countBySeverity(findings: Finding[]): Record<Severity, number> {
  return {
    high: findings.filter((f) => f.severity === "high").length,
    medium: findings.filter((f) => f.severity === "medium").length,
    low: findings.filter((f) => f.severity === "low").length,
  };
}

function rate(findings: Finding[]): number | null {
  if (findings.length === 0) return null;
  const ok = findings.filter(
    (f) => f.verdict === "compliant" || f.status === "approved",
  ).length;
  return Math.round((ok / findings.length) * 100);
}

function demoRunList(): RunListItem[] {
  return demo.DEMO_RUNS.map((r) => ({
    ...r,
    submissionTitle:
      demo.DEMO_SUBMISSIONS.find((s) => s.id === r.submission_id)?.title ??
      "Untitled",
    findingsCount: demo.DEMO_FINDINGS.filter((f) => f.run_id === r.id).length,
  })).sort((a, b) => b.created_at.localeCompare(a.created_at));
}

type RunRow = AnalysisRun & {
  submissions: { title: string | null } | null;
  findings: { count: number }[] | null;
};

function mapRunRows(rows: unknown[]): RunListItem[] {
  return (rows as RunRow[]).map((r) => ({
    ...r,
    submissionTitle: r.submissions?.title ?? "Untitled",
    findingsCount: r.findings?.[0]?.count ?? 0,
  }));
}

// ── Submissions ──────────────────────────────────────────────────────────────

export interface SubmissionListItem extends Submission {
  assetKinds: AssetKind[];
  latestRun: Pick<AnalysisRun, "id" | "status" | "model_id" | "created_at"> | null;
}

export async function getSubmissions(
  orgId: string,
): Promise<SubmissionListItem[]> {
  if (isDemoMode) {
    return demo.DEMO_SUBMISSIONS.map((s) => ({
      ...s,
      assetKinds: demo.DEMO_ASSETS.filter(
        (a) => a.submission_id === s.id,
      ).map((a) => a.kind),
      latestRun:
        demo.DEMO_RUNS.find((r) => r.submission_id === s.id) ?? null,
    })).sort((a, b) => b.created_at.localeCompare(a.created_at));
  }

  const supabase = await createClient();
  const { data } = await supabase
    .from("submissions")
    .select("*, assets(kind), analysis_runs(id, status, model_id, created_at)")
    .eq("org_id", orgId)
    .order("created_at", { ascending: false })
    .limit(100);

  type Row = Submission & {
    assets: { kind: AssetKind }[] | null;
    analysis_runs: Pick<
      AnalysisRun,
      "id" | "status" | "model_id" | "created_at"
    >[] | null;
  };

  return ((data ?? []) as Row[]).map((row) => {
    const runs = [...(row.analysis_runs ?? [])].sort((a, b) =>
      b.created_at.localeCompare(a.created_at),
    );
    return {
      ...row,
      assetKinds: (row.assets ?? []).map((a) => a.kind),
      latestRun: runs[0] ?? null,
    };
  });
}

// ── Runs / reports ───────────────────────────────────────────────────────────

export async function getRuns(orgId: string): Promise<RunListItem[]> {
  if (isDemoMode) return demoRunList();

  const supabase = await createClient();
  const { data } = await supabase
    .from("analysis_runs")
    .select("*, submissions(title), findings(count)")
    .eq("org_id", orgId)
    .order("created_at", { ascending: false })
    .limit(100);
  return mapRunRows(data ?? []);
}

export interface RunDetail {
  run: AnalysisRun;
  submission: Submission;
  assets: Asset[];
  findings: Finding[];
  layerOutputs: LayerOutput[];
  /** asset id → short-lived signed URL for previewable files */
  assetUrls: Record<string, string>;
}

export async function getRunDetail(runId: string): Promise<RunDetail | null> {
  if (isDemoMode) {
    const run = demo.DEMO_RUNS.find((r) => r.id === runId);
    if (!run) return null;
    const submission = demo.DEMO_SUBMISSIONS.find(
      (s) => s.id === run.submission_id,
    )!;
    return {
      run,
      submission,
      assets: demo.DEMO_ASSETS.filter(
        (a) => a.submission_id === submission.id,
      ),
      findings: demo.DEMO_FINDINGS.filter((f) => f.run_id === runId),
      layerOutputs: demo.DEMO_LAYER_OUTPUTS.filter((l) => l.run_id === runId),
      assetUrls: {},
    };
  }

  const supabase = await createClient();
  const { data: run } = await supabase
    .from("analysis_runs")
    .select("*")
    .eq("id", runId)
    .maybeSingle();
  if (!run) return null;

  const [submission, assets, findings, layers] = await Promise.all([
    supabase
      .from("submissions")
      .select("*")
      .eq("id", run.submission_id)
      .single()
      .then((r) => r.data),
    supabase
      .from("assets")
      .select("*")
      .eq("submission_id", run.submission_id)
      .then((r) => (r.data ?? []) as Asset[]),
    supabase
      .from("findings")
      .select("*")
      .eq("run_id", runId)
      .order("created_at", { ascending: true })
      .then((r) => (r.data ?? []) as Finding[]),
    supabase
      .from("layer_outputs")
      .select("*")
      .eq("run_id", runId)
      .then((r) => (r.data ?? []) as LayerOutput[]),
  ]);
  if (!submission) return null;

  // Signed URLs for previewable uploads (never served from the app origin).
  const assetUrls: Record<string, string> = {};
  await Promise.all(
    assets
      .filter((a) => a.storage_path && (a.kind === "image" || a.kind === "pdf"))
      .map(async (a) => {
        const { data } = await supabase.storage
          .from("assets")
          .createSignedUrl(a.storage_path!, 600);
        if (data?.signedUrl) assetUrls[a.id] = data.signedUrl;
      }),
  );

  return {
    run: run as AnalysisRun,
    submission: submission as Submission,
    assets,
    findings,
    layerOutputs: layers,
    assetUrls,
  };
}

// ── Members / API keys / usage / plans ───────────────────────────────────────

export interface MemberRow {
  org_id: string;
  user_id: string;
  role: Role;
  created_at: string;
  email: string;
}

export async function getMembers(orgId: string): Promise<MemberRow[]> {
  if (isDemoMode) return demo.DEMO_MEMBERS;

  const supabase = await createClient();
  const { data } = await supabase
    .from("memberships")
    .select("org_id, user_id, role, created_at")
    .eq("org_id", orgId)
    .order("created_at", { ascending: true });

  const rows = (data ?? []) as Omit<MemberRow, "email">[];

  // Emails live in auth.users, which RLS clients cannot read — resolve them
  // with the service role when available, otherwise show shortened ids.
  const admin = createAdminClient();
  const emails = new Map<string, string>();
  if (admin) {
    await Promise.all(
      rows.slice(0, 50).map(async (m) => {
        const { data: u } = await admin.auth.admin.getUserById(m.user_id);
        if (u?.user?.email) emails.set(m.user_id, u.user.email);
      }),
    );
  }
  return rows.map((m) => ({
    ...m,
    email: emails.get(m.user_id) ?? `${m.user_id.slice(0, 8)}…`,
  }));
}

export async function getApiKeys(orgId: string): Promise<ApiKey[]> {
  if (isDemoMode) return demo.DEMO_API_KEYS;
  const supabase = await createClient();
  const { data } = await supabase
    .from("api_keys")
    .select("id, org_id, name, scopes, created_at, last_used_at, revoked_at")
    .eq("org_id", orgId)
    .order("created_at", { ascending: false });
  return (data ?? []) as ApiKey[];
}

export interface UsageSummary {
  events: UsageEvent[];
  periodCostCents: number;
  periodTokens: number;
}

export async function getUsageSummary(
  orgId: string,
  periodStartIso: string | null,
): Promise<UsageSummary> {
  if (isDemoMode) {
    return {
      events: demo.DEMO_USAGE,
      periodCostCents: demo.DEMO_PERIOD_COST_CENTS,
      periodTokens: demo.DEMO_PERIOD_TOKENS,
    };
  }

  const supabase = await createClient();
  const monthStart = new Date();
  monthStart.setUTCDate(1);
  monthStart.setUTCHours(0, 0, 0, 0);
  const since = periodStartIso ?? monthStart.toISOString();

  const { data } = await supabase
    .from("usage_events")
    .select("*")
    .eq("org_id", orgId)
    .gte("created_at", since)
    .order("created_at", { ascending: false })
    .limit(500);

  const events = (data ?? []) as UsageEvent[];
  return {
    events: events.slice(0, 20),
    periodCostCents: events.reduce((s, e) => s + (e.cost_cents ?? 0), 0),
    periodTokens: events.reduce(
      (s, e) => s + (e.input_tokens ?? 0) + (e.output_tokens ?? 0),
      0,
    ),
  };
}

export async function getPlans(): Promise<PlanEntitlement[]> {
  if (!isDemoMode) {
    const supabase = await createClient();
    const { data } = await supabase.from("plan_entitlements").select("*");
    if (data && data.length > 0) {
      const byTier = new Map(data.map((p) => [p.tier, p as PlanEntitlement]));
      return TIERS.map((t) => byTier.get(t) ?? ENTITLEMENTS[t]);
    }
  }
  return TIERS.map((t) => ENTITLEMENTS[t]);
}

export type { RunStatus };

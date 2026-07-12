// Row shapes mirroring supabase/migrations/0001_saas_core.sql — keep in sync.

export type Role = "owner" | "admin" | "reviewer" | "viewer";
export type Tier = "free" | "hobby" | "pro" | "design" | "enterprise";

export type RunStatus =
  | "queued"
  | "running_cv"
  | "running_nlp"
  | "running_llm"
  | "running_rules"
  | "reconciling"
  | "complete"
  | "failed";

export type Severity = "high" | "medium" | "low";
export type Verdict = "potential_violation" | "needs_review" | "compliant";
export type FindingStatus = "open" | "approved" | "flagged" | "dismissed";
export type AssetKind = "pdf" | "image" | "text" | "html" | "url" | "video";
export type ScanStatus = "pending" | "clean" | "infected" | "error";
export type SubscriptionStatus =
  | "trialing"
  | "active"
  | "past_due"
  | "canceled"
  | "incomplete"
  | "unpaid";

export interface Org {
  id: string;
  name: string;
  created_at: string;
}

export interface Membership {
  org_id: string;
  user_id: string;
  role: Role;
  created_at: string;
}

export interface Subscription {
  org_id: string;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  tier: Tier;
  status: SubscriptionStatus;
  current_period_start: string | null;
  current_period_end: string | null;
}

export interface PlanEntitlement {
  tier: Tier;
  llm_provider: string;
  llm_model: string;
  max_output_tokens: number;
  scans_per_month: number | null; // null = custom / uncapped
  seats: number | null;
  api_access: boolean;
  sso: boolean;
  sla: boolean;
  frameworks: "all" | string[];
}

export interface Submission {
  id: string;
  org_id: string;
  created_by: string;
  title: string | null;
  created_at: string;
}

export interface Asset {
  id: string;
  submission_id: string;
  org_id: string;
  kind: AssetKind;
  storage_path: string | null;
  source_url: string | null;
  checksum: string | null;
  scan_status: ScanStatus;
  created_at: string;
}

export interface AnalysisRun {
  id: string;
  submission_id: string;
  org_id: string;
  status: RunStatus;
  tier: Tier | null;
  model_id: string | null;
  prompt_version: string | null;
  rulepack_version: string | null;
  rag_corpus_hash: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_cents: number | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface FindingLocation {
  segment_ids?: string[];
  entity_ids?: string[];
  bbox?: { x: number; y: number; width: number; height: number };
}

export interface Finding {
  id: string;
  run_id: string;
  org_id: string;
  framework: string;
  rule_ref: string | null;
  severity: Severity;
  verdict: Verdict;
  confidence: number | null;
  location: FindingLocation | null;
  message: string;
  quoted_evidence?: string | null; // convenience: some engines store it in location/meta
  remediation: string | null;
  status: FindingStatus;
  reviewed_by: string | null;
  created_at: string;
}

export interface LayerOutput {
  run_id: string;
  org_id: string;
  layer: "cv" | "nlp" | "llm" | "rule";
  payload: Record<string, unknown>;
  created_at: string;
}

export interface UsageEvent {
  id: number;
  org_id: string;
  run_id: string | null;
  kind: "scan" | "token_spend" | "api_call" | "storage";
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_cents: number | null;
  created_at: string;
}

export interface ApiKey {
  id: string;
  org_id: string;
  name: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface Quota {
  tier: Tier;
  model: string;
  limit: number | null; // null = custom / uncapped
  used: number;
  remaining: number | null;
  api_access: boolean;
  period_end: string | null;
}

export interface OrgSummary {
  id: string;
  name: string;
  role: Role;
}

export interface SessionContext {
  user: { id: string; email: string };
  org: OrgSummary;
  orgs: OrgSummary[];
  role: Role;
  quota: Quota;
  subscription: Pick<
    Subscription,
    "tier" | "status" | "current_period_end" | "stripe_customer_id"
  >;
  demo: boolean;
}

export type ActionResult<T = undefined> =
  | { ok: true; data?: T; message?: string }
  | { ok: false; message: string };

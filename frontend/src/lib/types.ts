/** Typed mirror of the FastAPI surface (backend/app/routes + engine/report.py).
 * Response documents originating in the engine are persisted JSON — fields are
 * optional-tolerant so a report never crashes the renderer. */

export type Role = "viewer" | "reviewer" | "admin" | "owner";
export type Tier = "free" | "hobby" | "pro" | "design" | "enterprise";

export type RunStatus =
  | "queued"
  | "running_cv"
  | "running_nlp"
  | "running_llm"
  | "running_rules"
  | "reconciling"
  | "complete"
  | "human_review"
  | "failed";

export const ACTIVE_RUN_STATUSES: RunStatus[] = [
  "queued",
  "running_cv",
  "running_nlp",
  "running_llm",
  "running_rules",
  "reconciling",
];

export type Severity = "high" | "medium" | "low";
export type Verdict = "potential_violation" | "needs_review" | "compliant";
export type FindingStatus = "open" | "approved" | "flagged" | "dismissed";

// ---------------------------------------------------------------- orgs

export interface Entitlements {
  llm_model?: string | null;
  max_output_tokens?: number | null;
  credits_per_month?: number | null;
  api_rpm?: number | null;
  api_burst?: number | null;
  user_rpm?: number | null;
  max_concurrent_runs?: number | null;
  max_upload_mb?: number | null;
  submissions_per_day?: number | null;
  credit_packs_allowed?: boolean | null;
  api_access?: boolean | null;
  seats?: number | null;
  sso?: boolean | null;
  sla?: string | null;
  allowed_kinds?: string[] | null;
  max_video_seconds?: number | null;
}

export interface Membership {
  org_id: string;
  role: Role;
}

export interface OrgMe {
  org: { id: string; name: string; created_at: string };
  role: Role;
  tier: Tier;
  entitlements: Entitlements;
  credits: CreditBalance;
  memberships: Membership[];
}

export interface MemberRow {
  user_id: string;
  role: Role;
  created_at: string;
  email: string;
}

// ---------------------------------------------------------------- credits

export interface PriceList {
  text?: number;
  image?: number;
  html?: number;
  carousel_card?: number;
  pdf?: number;
  docx?: number;
  video?: number;
}

/** Units the engine meters effort in (migration 0012). */
export type EffortUnit =
  | "llm_input_1k"
  | "llm_output_1k"
  | "llm_call"
  | "ocr_page"
  | "cv_frame"
  | "video_second"
  | "rag_query"
  | "embed_1k";

export type EffortRates = Partial<Record<EffortUnit, number>>;

export interface CreditBalance {
  tier: Tier;
  subscription_credits: number;
  purchased_credits: number;
  /** Spendable now. Open holds are already debited, so this is post-reserve. */
  total: number;
  /** Escrowed by runs still in flight; part of it returns when they settle. */
  held: number;
  available: number;
  cycle_start: string | null;
  cycle_end: string | null;
  credits_per_month: number | null;
  /** Base price of a run — a floor, not the whole price (0012). */
  price_list: PriceList;
  effort_rates: EffortRates;
}

export interface LedgerEntry {
  id: number;
  delta: number;
  bucket: "subscription" | "purchased";
  reason:
    | "grant.cycle"
    | "grant.pack"
    | "grant.manual"
    | "consume.run"
    | "consume.tokens"
    | "consume.metered"
    | "hold.reserve"
    | "hold.release"
    | "refund.system_failure"
    | "adjust.manual"
    | "expire.cycle";
  run_id: string | null;
  stripe_ref: string | null;
  balance_after: number;
  created_at: string;
}

/** Live escrow state for one run. `status: "open"` means it is still moving. */
export interface RunCredits {
  reserved: number;
  floor_credits: number;
  metered: number;
  charged: number | null;
  returned: number | null;
  status: "open" | "settled" | "released";
  settled_at: string | null;
}

export interface EffortLineItem {
  unit: EffortUnit;
  quantity: number;
  rate: number;
  credits: number;
  events: number;
}

export interface RunEffort {
  units: EffortLineItem[];
  reserved: number | null;
  floor: number | null;
  metered: number | null;
  charged: number | null;
}

// ---------------------------------------------------------------- submissions

export type InlineKind = "text" | "html";
export type PricingKind = "text" | "html" | "image" | "carousel";

export interface SubmissionAccepted {
  submission_id: string;
  run_id: string;
  /** Escrowed for this run — an upper bound on the charge, not the charge. */
  credits_reserved: number;
  /** Base price component of the reserve. */
  credits_floor: number;
  /** @deprecated (0012) equals credits_reserved; read that instead. */
  credits_charged: number;
  balance: { subscription_credits: number; purchased_credits: number };
}

export interface SubmissionRow {
  id: string;
  title: string | null;
  created_by: string;
  target_jurisdictions: string[] | null;
  created_at: string;
}

export interface AssetRow {
  id: string;
  kind: "text" | "image" | "html";
  storage_path: string;
  checksum: string;
  scan_status: string;
  created_at: string;
}

export interface SubmissionDetail {
  submission: SubmissionRow & { params?: Record<string, unknown> };
  assets: AssetRow[];
  runs: RunRow[];
}

// ---------------------------------------------------------------- runs

export interface RunRow {
  id: string;
  submission_id: string;
  status: RunStatus;
  tier: Tier;
  model_id: string | null;
  engine_run_id?: string | null;
  resumed_from_run_id?: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunDetail extends RunRow {
  prompt_version: string | null;
  rulepack_version: string | null;
  rag_corpus_hash: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  /**
   * The org's own text: substantiation given at intake, or a reviewer's
   * guidance on a resume. Returned so the review conversation can be rebuilt
   * after a reload rather than lost.
   */
  operator_guidance: string | null;
  error: string | null;
}

export interface QueueInfo {
  job_status: string;
  attempts: number;
  not_before: string | null;
  last_error: string | null;
}

export interface RunResponse {
  run: RunDetail;
  queue: QueueInfo | null;
  /** Escrow state; updates live while status is "open". Null for pre-0012 runs. */
  credits: RunCredits | null;
  disclaimer: string;
}

// ------------------------------------------------------------ public plans

export interface PublicPlan {
  tier: Tier;
  name: string;
  tagline: string;
  monthly_usd_cents: number | null;
  credits_per_month: number | null;
  max_upload_mb: number;
  seats: number | null;
  api_access: boolean;
  credit_packs_allowed: boolean;
  allowed_kinds: string[];
  max_video_seconds: number | null;
  max_concurrent_runs: number;
  submissions_per_day: number | null;
  /** Base price per asset kind — the floor of a run, not its whole price. */
  credit_costs: Record<string, number>;
  /** Metered rates charged above the floor (0012). */
  effort_rates: EffortRates;
}

export interface PublicPlansResponse {
  plans: PublicPlan[];
  packs: { pack: string; credits: number; usd_cents: number }[];
  effort_rates: { tier: Tier; unit: EffortUnit; credits: number }[];
  /** @deprecated (0012) superseded by effort_rates. */
  token_rates: {
    tier: Tier;
    in_per_1k: number;
    out_per_1k: number;
    min_credits: number;
  }[];
}

// ------------------------------------------------------------ live activity

export type RunEventStage =
  | "queued"
  | "ingest"
  | "cv"
  | "nlp"
  | "retrieval"
  | "llm"
  | "rules"
  | "report"
  | "done"
  | "error";

export interface RunEvent {
  id: number;
  stage: RunEventStage;
  event: string;
  message: string;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface RunEventsResponse {
  events: RunEvent[];
  run_status: RunStatus;
  last_id: number;
}

// ---------------------------------------------------------------- report

export interface LlmFinding {
  finding_id?: string;
  framework?: string;
  severity?: Severity;
  verdict?: Verdict;
  cited_segment_ids?: string[];
  cited_entity_ids?: string[];
  quoted_evidence?: string | null;
  claim_candidate_id?: string | null;
  regulation_citations?: string[];
  reasoning?: string;
  scope_of_improvement?: string;
}

export interface LlmReview {
  asset_id?: string;
  findings?: LlmFinding[];
  reviewed_clear?: string[];
  frameworks_evaluated?: string[];
  llm_meta?: {
    model?: string;
    prompt_version?: string;
    rag_corpus_hash?: string;
    reviewed_at?: string;
    latency_ms?: number;
  };
}

export interface FailedCheck {
  check_id?: string;
  message?: string;
  severity?: string;
  instruction?: string;
  [key: string]: unknown;
}

export interface Verification {
  review_passed?: boolean;
  checks_run?: number;
  failed_checks?: FailedCheck[];
  asset_defects?: FailedCheck[];
  advisories?: FailedCheck[];
  ruleset_version?: string;
  ruleset_hash?: string;
}

export interface RoundAudit {
  round?: number;
  was_rule_engine_callback?: boolean;
  had_human_guidance?: boolean;
  feedback_sent_to_llm?: string | null;
  llm_review?: LlmReview;
  adapter_notes?: Record<string, unknown>[];
  rule_engine_passed?: boolean | null;
  failed_checks?: FailedCheck[];
}

export interface HumanReviewRequest {
  reason?: string;
  failed_checks?: FailedCheck[];
  instructions?: FailedCheck[];
  how_to_resume?: string;
}

export interface EngineReport {
  run_id?: string;
  asset_id?: string;
  tier?: string;
  status?: "passed" | "human_review" | "llm_error" | null;
  llm_rounds_used?: number;
  max_llm_rounds?: number;
  llm_review?: LlmReview | null;
  verification?: Verification | null;
  rounds?: RoundAudit[];
  human_review?: HumanReviewRequest | null;
  llm_error?: string | null;
  warnings?: string[];
  provenance?: Record<string, unknown>;
  timings_ms?: Record<string, number>;
  resumed_from_run_id?: string | null;
}

export interface ReportResponse {
  report: EngineReport;
  disclaimer: string;
}

// ---------------------------------------------------------------- findings

export interface FindingLocation {
  source?: "llm_review" | "rule_engine_asset_defect";
  finding_id?: string;
  cited_segment_ids?: string[];
  cited_entity_ids?: string[];
  claim_candidate_id?: string | null;
  quoted_evidence?: string | null;
  evidence?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface FindingRow {
  id: string;
  run_id: string;
  framework: string;
  rule_ref: string | null;
  severity: Severity;
  verdict: Verdict;
  location: FindingLocation | null;
  message: string;
  remediation: string | null;
  status: FindingStatus;
  reviewed_by: string | null;
  created_at: string;
}

// ---------------------------------------------------------------- api keys

export interface ApiKeyRow {
  id: string;
  name: string;
  scopes: string[];
  rate_limit_rpm: number | null;
  created_by: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface ApiKeyCreated {
  api_key: string;
  id: string;
  prefix: string;
  scopes: string[];
  note: string;
}

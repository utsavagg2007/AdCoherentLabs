import type {
  AnalysisRun,
  ApiKey,
  Asset,
  Finding,
  LayerOutput,
  Membership,
  OrgSummary,
  Quota,
  SessionContext,
  Submission,
  UsageEvent,
} from "@/lib/types";

/**
 * Fixture data for demo mode. Modelled on the engine's real contracts:
 * findings mirror rag-engine/sample_output-LLMresponse.json and the NLP
 * payload mirrors nlp-result-template.json.
 */

export const DEMO_USER = {
  id: "00000000-0000-4000-8000-00000000d001",
  email: "demo@adcoherentlabs.com",
};

const ORG_A = "00000000-0000-4000-8000-0000000000a1";
const ORG_B = "00000000-0000-4000-8000-0000000000b2";

export const DEMO_ORGS: OrgSummary[] = [
  { id: ORG_A, name: "Northwind Credit", role: "owner" },
  { id: ORG_B, name: "Atlas Trading Co", role: "viewer" },
];

export const DEMO_QUOTA: Quota = {
  tier: "pro",
  model: "claude-sonnet-5",
  limit: 1000,
  used: 412,
  remaining: 588,
  api_access: true,
  period_end: "2026-08-01T00:00:00Z",
};

export const DEMO_SESSION: SessionContext = {
  user: DEMO_USER,
  org: DEMO_ORGS[0],
  orgs: DEMO_ORGS,
  role: "owner",
  quota: DEMO_QUOTA,
  subscription: {
    tier: "pro",
    status: "active",
    current_period_end: "2026-08-01T00:00:00Z",
    stripe_customer_id: "cus_demo_northwind",
  },
  demo: true,
};

// ── Submissions & runs ───────────────────────────────────────────────────────

const SUB_REACH = "10000000-0000-4000-8000-000000000001";
const SUB_SAVINGS = "10000000-0000-4000-8000-000000000002";
const SUB_CRYPTO = "10000000-0000-4000-8000-000000000003";
const SUB_EMAIL = "10000000-0000-4000-8000-000000000004";
const SUB_ROBO = "10000000-0000-4000-8000-000000000005";

export const RUN_REACH = "20000000-0000-4000-8000-000000000001";
export const RUN_SAVINGS = "20000000-0000-4000-8000-000000000002";
export const RUN_CRYPTO = "20000000-0000-4000-8000-000000000003";
export const RUN_EMAIL = "20000000-0000-4000-8000-000000000004";
export const RUN_ROBO = "20000000-0000-4000-8000-000000000005";

export const DEMO_SUBMISSIONS: Submission[] = [
  {
    id: SUB_REACH,
    org_id: ORG_A,
    created_by: DEMO_USER.id,
    title: "Reach Personal Loan — Display Ad Q3",
    created_at: "2026-07-09T08:40:00Z",
  },
  {
    id: SUB_SAVINGS,
    org_id: ORG_A,
    created_by: DEMO_USER.id,
    title: "HighYield Savings — Landing Page",
    created_at: "2026-07-10T06:05:00Z",
  },
  {
    id: SUB_CRYPTO,
    org_id: ORG_A,
    created_by: DEMO_USER.id,
    title: "TradeSwift App — Store Listing Copy",
    created_at: "2026-07-10T06:55:00Z",
  },
  {
    id: SUB_EMAIL,
    org_id: ORG_A,
    created_by: DEMO_USER.id,
    title: "Instant Card — Email Campaign v2",
    created_at: "2026-07-08T14:20:00Z",
  },
  {
    id: SUB_ROBO,
    org_id: ORG_A,
    created_by: DEMO_USER.id,
    title: "Robo-Advisor Banner Set (3 sizes)",
    created_at: "2026-07-06T11:00:00Z",
  },
];

export const DEMO_ASSETS: Asset[] = [
  {
    id: "30000000-0000-4000-8000-000000000001",
    submission_id: SUB_REACH,
    org_id: ORG_A,
    kind: "image",
    storage_path: `${ORG_A}/${SUB_REACH}/f3a91c.png`,
    source_url: null,
    checksum: "sha256:9f2ce1…",
    scan_status: "clean",
    created_at: "2026-07-09T08:40:10Z",
  },
  {
    id: "30000000-0000-4000-8000-000000000002",
    submission_id: SUB_SAVINGS,
    org_id: ORG_A,
    kind: "url",
    storage_path: null,
    source_url: "https://highyield.example.com/savings",
    checksum: null,
    scan_status: "clean",
    created_at: "2026-07-10T06:05:05Z",
  },
  {
    id: "30000000-0000-4000-8000-000000000003",
    submission_id: SUB_CRYPTO,
    org_id: ORG_A,
    kind: "text",
    storage_path: `${ORG_A}/${SUB_CRYPTO}/b7d2ee.txt`,
    source_url: null,
    checksum: "sha256:4b01aa…",
    scan_status: "clean",
    created_at: "2026-07-10T06:55:03Z",
  },
  {
    id: "30000000-0000-4000-8000-000000000004",
    submission_id: SUB_EMAIL,
    org_id: ORG_A,
    kind: "html",
    storage_path: `${ORG_A}/${SUB_EMAIL}/c197f0.html`,
    source_url: null,
    checksum: "sha256:77e3d2…",
    scan_status: "infected",
    created_at: "2026-07-08T14:20:08Z",
  },
  {
    id: "30000000-0000-4000-8000-000000000005",
    submission_id: SUB_ROBO,
    org_id: ORG_A,
    kind: "image",
    storage_path: `${ORG_A}/${SUB_ROBO}/aa20cd.png`,
    source_url: null,
    checksum: "sha256:be44f9…",
    scan_status: "clean",
    created_at: "2026-07-06T11:00:12Z",
  },
];

export const DEMO_RUNS: AnalysisRun[] = [
  {
    id: RUN_REACH,
    submission_id: SUB_REACH,
    org_id: ORG_A,
    status: "complete",
    tier: "pro",
    model_id: "claude-sonnet-5",
    prompt_version: "compliance-review-v1.3",
    rulepack_version: "ftc-us-2026.06",
    rag_corpus_hash: "9c41d2ab77e01f45",
    input_tokens: 48210,
    output_tokens: 3120,
    cost_cents: 62,
    error: null,
    started_at: "2026-07-09T08:40:31Z",
    finished_at: "2026-07-09T08:41:47Z",
    created_at: "2026-07-09T08:40:12Z",
  },
  {
    id: RUN_SAVINGS,
    submission_id: SUB_SAVINGS,
    org_id: ORG_A,
    status: "running_llm",
    tier: "pro",
    model_id: "claude-sonnet-5",
    prompt_version: "compliance-review-v1.3",
    rulepack_version: "ftc-us-2026.06",
    rag_corpus_hash: "9c41d2ab77e01f45",
    input_tokens: null,
    output_tokens: null,
    cost_cents: null,
    error: null,
    started_at: "2026-07-10T06:05:41Z",
    finished_at: null,
    created_at: "2026-07-10T06:05:12Z",
  },
  {
    id: RUN_CRYPTO,
    submission_id: SUB_CRYPTO,
    org_id: ORG_A,
    status: "queued",
    tier: "pro",
    model_id: null,
    prompt_version: null,
    rulepack_version: null,
    rag_corpus_hash: null,
    input_tokens: null,
    output_tokens: null,
    cost_cents: null,
    error: null,
    started_at: null,
    finished_at: null,
    created_at: "2026-07-10T06:55:10Z",
  },
  {
    id: RUN_EMAIL,
    submission_id: SUB_EMAIL,
    org_id: ORG_A,
    status: "failed",
    tier: "pro",
    model_id: null,
    prompt_version: null,
    rulepack_version: null,
    rag_corpus_hash: null,
    input_tokens: null,
    output_tokens: null,
    cost_cents: null,
    error: "Asset failed malware scan (scan_status=infected); run aborted before Layer 1.",
    started_at: "2026-07-08T14:20:30Z",
    finished_at: "2026-07-08T14:20:32Z",
    created_at: "2026-07-08T14:20:11Z",
  },
  {
    id: RUN_ROBO,
    submission_id: SUB_ROBO,
    org_id: ORG_A,
    status: "complete",
    tier: "pro",
    model_id: "claude-sonnet-5",
    prompt_version: "compliance-review-v1.2",
    rulepack_version: "sec-us-2026.05",
    rag_corpus_hash: "5510efac2290bd18",
    input_tokens: 30110,
    output_tokens: 1980,
    cost_cents: 41,
    error: null,
    started_at: "2026-07-06T11:00:40Z",
    finished_at: "2026-07-06T11:01:38Z",
    created_at: "2026-07-06T11:00:15Z",
  },
];

// ── Findings (Reach Personal Loan run — from the real sample LLM output) ────

export const DEMO_FINDINGS: Finding[] = [
  {
    id: "40000000-0000-4000-8000-000000000001",
    run_id: RUN_REACH,
    org_id: ORG_A,
    framework: "TILA",
    rule_ref: "12 CFR 1026.24(d)",
    severity: "high",
    verdict: "potential_violation",
    confidence: 0.86,
    location: {
      segment_ids: ["seg_5", "seg_7"],
      bbox: { x: 0.05, y: 0.78, width: 0.9, height: 0.16 },
    },
    message:
      "The ad states a monthly payment amount ($1,068) and repayment term (60 months), which are triggering terms under 12 CFR 1026.24(d). The required APR disclosure exists but sits in a dense fine-print block; whether it satisfies clear-and-conspicuous prominence relative to the triggering terms requires CV prominence evidence (contrast, text height) to resolve.",
    quoted_evidence:
      "*Example table shows calculations based on a $40,000 Reach Personal Loan with a fixed rate of 20.39% APR and a 60-month term.",
    remediation:
      "Move the APR and terms disclosure adjacent to the payment claim, render it at ≥ 8px with WCAG-AA contrast, and repeat the APR wherever a triggering term appears.",
    status: "open",
    reviewed_by: null,
    created_at: "2026-07-09T08:41:40Z",
  },
  {
    id: "40000000-0000-4000-8000-000000000002",
    run_id: RUN_REACH,
    org_id: ORG_A,
    framework: "FTC",
    rule_ref: "FTC Act §5",
    severity: "medium",
    verdict: "potential_violation",
    confidence: 0.74,
    location: {
      segment_ids: ["seg_2"],
      bbox: { x: 0.05, y: 0.3, width: 0.9, height: 0.14 },
    },
    message:
      "The headline performance claim '8.3 times faster' generalizes from a single hypothetical example (496 vs 60 months at assumed APRs). Under FTC Act Section 5 the advertiser needs substantiation that this is typical for consumers; the disclosure describes the example's assumptions but does not state typicality.",
    quoted_evidence: "Pay down debt 8.3 times faster with Reach Personal Loan",
    remediation:
      "Either substantiate typicality with portfolio data or qualify the claim in the headline itself (e.g. 'up to', with the basis disclosed adjacent to the claim).",
    status: "open",
    reviewed_by: null,
    created_at: "2026-07-09T08:41:41Z",
  },
  {
    id: "40000000-0000-4000-8000-000000000003",
    run_id: RUN_REACH,
    org_id: ORG_A,
    framework: "FTC",
    rule_ref: "FTC Act §5 (substantiation)",
    severity: "low",
    verdict: "compliant",
    confidence: 0.9,
    location: {
      segment_ids: ["seg_6", "seg_7"],
      bbox: { x: 0.05, y: 0.55, width: 0.42, height: 0.12 },
    },
    message:
      "The comparative savings figure is asterisk-linked to a disclosure that states the calculation basis, the data source for the credit-card comparison (average APR of 25.33%, Forbes 2025), and a variability caveat. The claim is adequately qualified as an example-based comparison.",
    quoted_evidence: "*72% Savings in total interest paid",
    remediation: null,
    status: "approved",
    reviewed_by: DEMO_USER.id,
    created_at: "2026-07-09T08:41:42Z",
  },
  {
    id: "40000000-0000-4000-8000-000000000004",
    run_id: RUN_REACH,
    org_id: ORG_A,
    framework: "CFPB",
    rule_ref: "UDAAP",
    severity: "low",
    verdict: "compliant",
    confidence: 0.88,
    location: {
      segment_ids: ["seg_7"],
      bbox: { x: 0.53, y: 0.55, width: 0.42, height: 0.12 },
    },
    message:
      "No UDAAP concern beyond the FTC/TILA items already raised: the representative-example basis is disclosed (median funded APR with date range), the comparison methodology is sourced, and consumer-variability language is present.",
    quoted_evidence:
      "Your actual rate, payment amount, and total interest may vary based on your credit history, loan amount, and loan term.",
    remediation: null,
    status: "open",
    reviewed_by: null,
    created_at: "2026-07-09T08:41:43Z",
  },
  // Robo-advisor run — clean result
  {
    id: "40000000-0000-4000-8000-000000000005",
    run_id: RUN_ROBO,
    org_id: ORG_A,
    framework: "SEC",
    rule_ref: "Marketing Rule 206(4)-1",
    severity: "low",
    verdict: "compliant",
    confidence: 0.92,
    location: { segment_ids: ["seg_1"] },
    message:
      "Performance language is hypothetical-free and the required 'investing involves risk' legend is present at compliant prominence in all three banner sizes.",
    quoted_evidence: "Investing involves risk, including possible loss of principal.",
    remediation: null,
    status: "approved",
    reviewed_by: DEMO_USER.id,
    created_at: "2026-07-06T11:01:30Z",
  },
];

// Findings revealed at the end of the demo "live run" simulation.
export const DEMO_LIVE_FINDINGS: Finding[] = [
  {
    id: "40000000-0000-4000-8000-000000000101",
    run_id: RUN_SAVINGS,
    org_id: ORG_A,
    framework: "Reg_DD",
    rule_ref: "12 CFR 1030.8(b)",
    severity: "high",
    verdict: "potential_violation",
    confidence: 0.83,
    location: { segment_ids: ["seg_1"], bbox: { x: 0.05, y: 0.08, width: 0.9, height: 0.12 } },
    message:
      "The headline advertises '4.50% APY' but the page never states that the rate is variable or the minimum balance required to obtain it — both mandatory when an APY is advertised under Reg DD §1030.8(b).",
    quoted_evidence: "Earn 4.50% APY on every dollar",
    remediation:
      "Add the 'Rates may change after account opening' and minimum-balance disclosures adjacent to the APY claim.",
    status: "open",
    reviewed_by: null,
    created_at: "2026-07-10T06:08:00Z",
  },
  {
    id: "40000000-0000-4000-8000-000000000102",
    run_id: RUN_SAVINGS,
    org_id: ORG_A,
    framework: "FTC",
    rule_ref: "FTC Act §5",
    severity: "medium",
    verdict: "needs_review",
    confidence: 0.61,
    location: { segment_ids: ["seg_3"], bbox: { x: 0.05, y: 0.45, width: 0.9, height: 0.1 } },
    message:
      "'No fees, ever' conflicts with the fee schedule linked in the footer (outgoing wire fee). Whether the qualifier is sufficiently proximate needs human review.",
    quoted_evidence: "No fees, ever.",
    remediation:
      "Qualify the claim ('No monthly maintenance fees') or remove fees that contradict it.",
    status: "open",
    reviewed_by: null,
    created_at: "2026-07-10T06:08:01Z",
  },
];

// ── Layer outputs for the Reach run (provenance tab) ─────────────────────────

export const DEMO_LAYER_OUTPUTS: LayerOutput[] = [
  {
    run_id: RUN_REACH,
    org_id: ORG_A,
    layer: "cv",
    created_at: "2026-07-09T08:40:52Z",
    payload: {
      text_blocks: 9,
      visual_findings: [
        {
          type: "fine_print",
          detail: "Disclosure block rendered at 7.2px, contrast 4.8:1, below the fold",
          severity_hint: "medium",
        },
      ],
      asset_meta: { kind: "banner", dimensions: "1200x1200", frames_sampled: 1 },
      ocr_engine: "tesseract-5.3",
    },
  },
  {
    run_id: RUN_REACH,
    org_id: ORG_A,
    layer: "nlp",
    created_at: "2026-07-09T08:41:04Z",
    payload: {
      segments: 9,
      claim_candidates: 5,
      entities: 11,
      routing: {
        product_type: "personal_loan",
        frameworks: ["TILA", "FTC", "CFPB"],
        signal: "payment amount + term in creative -> TILA; performance claim -> FTC",
      },
      embedding_model: "text-embedding-3-large",
    },
  },
  {
    run_id: RUN_REACH,
    org_id: ORG_A,
    layer: "llm",
    created_at: "2026-07-09T08:41:39Z",
    payload: {
      model: "claude-sonnet-5",
      prompt_version: "compliance-review-v1.3",
      rag_corpus_hash: "9c41d2ab77e01f45",
      findings: 4,
      reviewed_clear: ["clm_1", "clm_4", "seg_1", "seg_3"],
      frameworks_evaluated: ["TILA", "FTC", "CFPB"],
      latency_ms: 14210,
    },
  },
  {
    run_id: RUN_REACH,
    org_id: ORG_A,
    layer: "rule",
    created_at: "2026-07-09T08:41:46Z",
    payload: {
      rulepack_version: "ftc-us-2026.06",
      rules_evaluated: 38,
      reconciliation: { confirmed: 2, overridden: 0, escalated: 0, passed: 2 },
      note: "LLM findings llmf_001/llmf_002 confirmed by deterministic checks; no overrides.",
    },
  },
];

// ── Members / keys / usage ───────────────────────────────────────────────────

export interface MemberRow extends Membership {
  email: string;
}

export const DEMO_MEMBERS: MemberRow[] = [
  {
    org_id: ORG_A,
    user_id: DEMO_USER.id,
    role: "owner",
    created_at: "2026-06-02T09:00:00Z",
    email: DEMO_USER.email,
  },
  {
    org_id: ORG_A,
    user_id: "00000000-0000-4000-8000-00000000d002",
    role: "admin",
    created_at: "2026-06-03T10:00:00Z",
    email: "priya@northwindcredit.com",
  },
  {
    org_id: ORG_A,
    user_id: "00000000-0000-4000-8000-00000000d003",
    role: "reviewer",
    created_at: "2026-06-10T15:30:00Z",
    email: "marco@northwindcredit.com",
  },
  {
    org_id: ORG_A,
    user_id: "00000000-0000-4000-8000-00000000d004",
    role: "viewer",
    created_at: "2026-06-21T08:45:00Z",
    email: "legal@northwindcredit.com",
  },
];

export const DEMO_API_KEYS: ApiKey[] = [
  {
    id: "50000000-0000-4000-8000-000000000001",
    org_id: ORG_A,
    name: "CI pipeline",
    scopes: ["submit", "read"],
    created_at: "2026-06-15T12:00:00Z",
    last_used_at: "2026-07-10T05:12:00Z",
    revoked_at: null,
  },
  {
    id: "50000000-0000-4000-8000-000000000002",
    org_id: ORG_A,
    name: "Staging (rotated)",
    scopes: ["read"],
    created_at: "2026-06-05T12:00:00Z",
    last_used_at: "2026-06-28T18:40:00Z",
    revoked_at: "2026-06-30T09:00:00Z",
  },
];

export const DEMO_USAGE: UsageEvent[] = [
  {
    id: 9012,
    org_id: ORG_A,
    run_id: RUN_REACH,
    kind: "token_spend",
    model: "claude-sonnet-5",
    input_tokens: 48210,
    output_tokens: 3120,
    cost_cents: 62,
    created_at: "2026-07-09T08:41:47Z",
  },
  {
    id: 9013,
    org_id: ORG_A,
    run_id: RUN_ROBO,
    kind: "token_spend",
    model: "claude-sonnet-5",
    input_tokens: 30110,
    output_tokens: 1980,
    cost_cents: 41,
    created_at: "2026-07-06T11:01:38Z",
  },
  {
    id: 9014,
    org_id: ORG_A,
    run_id: RUN_REACH,
    kind: "scan",
    model: null,
    input_tokens: null,
    output_tokens: null,
    cost_cents: null,
    created_at: "2026-07-09T08:40:12Z",
  },
];

/** Monthly token cost used on the billing page in demo mode. */
export const DEMO_PERIOD_COST_CENTS = 2418;
export const DEMO_PERIOD_TOKENS = 14_882_000;

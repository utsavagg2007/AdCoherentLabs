import type { FindingStatus, RunStatus, Severity, Verdict } from "./types";

/** Human-readable progress rail for a run. Order matters. */
export const RUN_STAGES: { status: RunStatus; label: string; hint: string }[] = [
  { status: "queued", label: "Preparing review", hint: "Queued for a worker" },
  {
    status: "running_cv",
    label: "Extracting creative evidence",
    hint: "OCR and computer vision over the creative",
  },
  {
    status: "running_nlp",
    label: "Identifying claims and disclosures",
    hint: "Segments, claims, entities, disclosures",
  },
  {
    status: "running_llm",
    label: "Grounding the review",
    hint: "Regulation-grounded AI review with citations",
  },
  {
    status: "running_rules",
    label: "Verifying findings",
    hint: "Deterministic checks over the review",
  },
  {
    status: "reconciling",
    label: "Finalizing report",
    hint: "Assembling the auditable report",
  },
];

export function runStageIndex(status: RunStatus): number {
  const i = RUN_STAGES.findIndex((s) => s.status === status);
  if (i >= 0) return i;
  return RUN_STAGES.length; // terminal states sit past the rail
}

export const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  queued: "Queued",
  running_cv: "Extracting evidence",
  running_nlp: "Identifying claims",
  running_llm: "Grounding review",
  running_rules: "Verifying findings",
  reconciling: "Finalizing",
  complete: "Complete",
  human_review: "Needs human review",
  failed: "Failed",
};

export function runStatusTone(
  status: RunStatus
): "active" | "good" | "warn" | "bad" {
  if (status === "complete") return "good";
  if (status === "human_review") return "warn";
  if (status === "failed") return "bad";
  return "active";
}

export const SEVERITY_LABEL: Record<Severity, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

export const SEVERITY_ORDER: Severity[] = ["high", "medium", "low"];

export const VERDICT_LABEL: Record<Verdict, string> = {
  potential_violation: "Potential violation",
  needs_review: "Needs review",
  compliant: "Compliant",
};

export const FINDING_STATUS_LABEL: Record<FindingStatus, string> = {
  open: "Open",
  approved: "Approved",
  flagged: "Flagged",
  dismissed: "Dismissed",
};

export const LEDGER_REASON_LABEL: Record<string, string> = {
  "grant.cycle": "Monthly allowance",
  "grant.pack": "Credit pack",
  "grant.manual": "Manual grant",
  "consume.run": "Review run",
  "refund.system_failure": "Refund — system failure",
  "adjust.manual": "Manual adjustment",
  "expire.cycle": "Cycle expiry",
};

export const FRAMEWORK_LABEL: Record<string, string> = {
  FTC: "FTC Act §5",
  TILA: "TILA / Regulation Z",
  REG_DD: "Regulation DD",
  CFPB: "CFPB / UDAAP",
  STATE_UDAP: "State UDAP",
  FDIC: "FDIC advertising",
  RULE_ENGINE: "Deterministic check",
};

export function frameworkLabel(code: string | null | undefined): string {
  if (!code) return "—";
  return FRAMEWORK_LABEL[code] ?? code;
}

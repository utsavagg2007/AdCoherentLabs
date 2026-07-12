import type { RunStatus, Severity, Verdict } from "./types";

export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function formatDate(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatDateTime(iso: string | null | undefined) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function timeAgo(iso: string | null | undefined) {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function formatCents(cents: number | null | undefined) {
  if (cents == null) return "—";
  return `$${(cents / 100).toFixed(2)}`;
}

export function formatTokens(n: number | null | undefined) {
  if (n == null) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

export function runDuration(
  started: string | null,
  finished: string | null,
): string {
  if (!started || !finished) return "—";
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}

export const RUN_STATUS_LABEL: Record<RunStatus, string> = {
  queued: "Queued",
  running_cv: "Layer 1 · CV",
  running_nlp: "Layer 2 · NLP",
  running_llm: "Layer 3 · LLM",
  running_rules: "Layer 4 · Rules",
  reconciling: "Reconciling",
  complete: "Complete",
  failed: "Failed",
};

export function isRunActive(status: RunStatus) {
  return status !== "complete" && status !== "failed";
}

export const SEVERITY_ORDER: Severity[] = ["high", "medium", "low"];

export const SEVERITY_STYLE: Record<Severity, string> = {
  high: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  medium: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  low: "bg-sky-500/15 text-sky-300 border-sky-500/30",
};

export const VERDICT_LABEL: Record<Verdict, string> = {
  potential_violation: "Potential violation",
  needs_review: "Needs review",
  compliant: "Compliant",
};

export const VERDICT_STYLE: Record<Verdict, string> = {
  potential_violation: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  needs_review: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  compliant: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
};

export const FRAMEWORKS = [
  "FTC",
  "SEC",
  "SEBI",
  "RBI",
  "GDPR",
  "TILA",
  "CFPB",
  "Reg_DD",
] as const;

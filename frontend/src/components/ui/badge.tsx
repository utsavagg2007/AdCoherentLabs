import { cn } from "@/lib/utils";
import {
  FINDING_STATUS_LABEL,
  RUN_STATUS_LABEL,
  SEVERITY_LABEL,
  VERDICT_LABEL,
  runStatusTone,
} from "@/lib/labels";
import type { FindingStatus, RunStatus, Severity, Verdict } from "@/lib/types";

export function Badge({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-bold tracking-wide whitespace-nowrap",
        className
      )}
    >
      {children}
    </span>
  );
}

/** Semantic severity — the only place red/amber/green appear. */
export function SeverityBadge({ severity }: { severity: Severity }) {
  const styles: Record<Severity, string> = {
    high: "border-red-200 bg-red-50 text-red-700",
    medium: "border-amber-200 bg-amber-50 text-amber-800",
    low: "border-emerald-200 bg-emerald-50 text-emerald-700",
  };
  return <Badge className={styles[severity]}>{SEVERITY_LABEL[severity]}</Badge>;
}

export function SeverityDot({ severity }: { severity: Severity }) {
  const styles: Record<Severity, string> = {
    high: "bg-red-500",
    medium: "bg-amber-500",
    low: "bg-emerald-500",
  };
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2 shrink-0 rounded-full", styles[severity])}
    />
  );
}

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const styles: Record<Verdict, string> = {
    potential_violation: "border-red-200 bg-red-50 text-red-700",
    needs_review: "border-amber-200 bg-amber-50 text-amber-800",
    compliant: "border-emerald-200 bg-emerald-50 text-emerald-700",
  };
  return <Badge className={styles[verdict]}>{VERDICT_LABEL[verdict]}</Badge>;
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const tone = runStatusTone(status);
  const styles = {
    active: "border-violet-200 bg-violet-50 text-violet-700",
    good: "border-emerald-200 bg-emerald-50 text-emerald-700",
    warn: "border-amber-200 bg-amber-50 text-amber-800",
    bad: "border-red-200 bg-red-50 text-red-700",
  } as const;
  const active = tone === "active";
  return (
    <Badge className={styles[tone]}>
      {active && (
        <span
          aria-hidden
          className="size-1.5 animate-pulse-dot rounded-full bg-violet-500"
        />
      )}
      {RUN_STATUS_LABEL[status]}
    </Badge>
  );
}

export function FindingStatusBadge({ status }: { status: FindingStatus }) {
  const styles: Record<FindingStatus, string> = {
    open: "border-zinc-200 bg-zinc-50 text-zinc-600",
    approved: "border-emerald-200 bg-emerald-50 text-emerald-700",
    flagged: "border-amber-200 bg-amber-50 text-amber-800",
    dismissed: "border-zinc-200 bg-zinc-100 text-zinc-500",
  };
  return <Badge className={styles[status]}>{FINDING_STATUS_LABEL[status]}</Badge>;
}

/** Neutral chip for citations / frameworks / metadata. */
export function Chip({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-violet-200 bg-violet-50 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-violet-800",
        className
      )}
    >
      {children}
    </span>
  );
}

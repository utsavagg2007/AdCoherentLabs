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
    high: "border-red-400/25 bg-red-400/10 text-red-300",
    medium: "border-amber-400/25 bg-amber-400/10 text-amber-300",
    low: "border-emerald-400/25 bg-emerald-400/10 text-emerald-300",
  };
  return <Badge className={styles[severity]}>{SEVERITY_LABEL[severity]}</Badge>;
}

export function SeverityDot({ severity }: { severity: Severity }) {
  const styles: Record<Severity, string> = {
    high: "bg-red-400",
    medium: "bg-amber-400",
    low: "bg-emerald-400",
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
    potential_violation: "border-red-400/25 bg-red-400/10 text-red-300",
    needs_review: "border-amber-400/25 bg-amber-400/10 text-amber-300",
    compliant: "border-emerald-400/25 bg-emerald-400/10 text-emerald-300",
  };
  return <Badge className={styles[verdict]}>{VERDICT_LABEL[verdict]}</Badge>;
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const tone = runStatusTone(status);
  const styles = {
    active: "border-sky-400/25 bg-sky-400/10 text-sky-300",
    good: "border-emerald-400/25 bg-emerald-400/10 text-emerald-300",
    warn: "border-amber-400/25 bg-amber-400/10 text-amber-300",
    bad: "border-red-400/25 bg-red-400/10 text-red-300",
  } as const;
  const active = tone === "active";
  return (
    <Badge className={styles[tone]}>
      {active && (
        <span
          aria-hidden
          className="size-1.5 animate-pulse-dot rounded-full bg-sky-300"
        />
      )}
      {RUN_STATUS_LABEL[status]}
    </Badge>
  );
}

export function FindingStatusBadge({ status }: { status: FindingStatus }) {
  const styles: Record<FindingStatus, string> = {
    open: "border-white/12 bg-white/5 text-ink-700",
    approved: "border-emerald-400/25 bg-emerald-400/10 text-emerald-300",
    flagged: "border-amber-400/25 bg-amber-400/10 text-amber-300",
    dismissed: "border-white/10 bg-white/[0.03] text-ink-500",
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
        "inline-flex items-center gap-1 rounded-md border border-white/12 bg-white/6 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-ink-800",
        className
      )}
    >
      {children}
    </span>
  );
}

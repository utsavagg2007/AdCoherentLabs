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
    high: "border-fail-line bg-fail-soft text-fail",
    medium: "border-warn-line bg-warn-soft text-warn",
    low: "border-pass-line bg-pass-soft text-pass",
  };
  return <Badge className={styles[severity]}>{SEVERITY_LABEL[severity]}</Badge>;
}

export function SeverityDot({ severity }: { severity: Severity }) {
  const styles: Record<Severity, string> = {
    high: "bg-fail-solid",
    medium: "bg-warn-solid",
    low: "bg-pass-solid",
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
    potential_violation: "border-fail-line bg-fail-soft text-fail",
    needs_review: "border-warn-line bg-warn-soft text-warn",
    compliant: "border-pass-line bg-pass-soft text-pass",
  };
  return <Badge className={styles[verdict]}>{VERDICT_LABEL[verdict]}</Badge>;
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const tone = runStatusTone(status);
  const styles = {
    active: "border-live-line bg-live-soft text-live",
    good: "border-pass-line bg-pass-soft text-pass",
    warn: "border-warn-line bg-warn-soft text-warn",
    bad: "border-fail-line bg-fail-soft text-fail",
  } as const;
  const active = tone === "active";
  return (
    <Badge className={styles[tone]}>
      {active && (
        <span
          aria-hidden
          className="size-1.5 animate-pulse-dot rounded-full bg-live-solid"
        />
      )}
      {RUN_STATUS_LABEL[status]}
    </Badge>
  );
}

export function FindingStatusBadge({ status }: { status: FindingStatus }) {
  const styles: Record<FindingStatus, string> = {
    open: "border-line bg-tint text-muted",
    approved: "border-pass-line bg-pass-soft text-pass",
    flagged: "border-warn-line bg-warn-soft text-warn",
    dismissed: "border-line bg-tint text-subtle",
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
        "inline-flex items-center gap-1 rounded-md border border-line bg-tint px-1.5 py-0.5 font-mono text-[11px] font-semibold text-body",
        className
      )}
    >
      {children}
    </span>
  );
}

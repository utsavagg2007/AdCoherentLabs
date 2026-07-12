import { Badge } from "@/components/ui/badge";
import {
  cn,
  RUN_STATUS_LABEL,
  SEVERITY_STYLE,
  VERDICT_LABEL,
  VERDICT_STYLE,
  isRunActive,
} from "@/lib/utils";
import type { RunStatus, ScanStatus, Severity, Verdict } from "@/lib/types";

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <Badge className={cn("uppercase", SEVERITY_STYLE[severity])}>
      {severity}
    </Badge>
  );
}

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return <Badge className={VERDICT_STYLE[verdict]}>{VERDICT_LABEL[verdict]}</Badge>;
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const style =
    status === "complete"
      ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
      : status === "failed"
        ? "bg-rose-500/15 text-rose-300 border-rose-500/30"
        : status === "queued"
          ? "bg-raised text-ink-dim border-line-bright"
          : "bg-violet-500/15 text-violet-300 border-violet-500/30";
  return (
    <Badge className={style}>
      {isRunActive(status) && status !== "queued" && (
        <span className="size-1.5 rounded-full bg-current animate-pulse-soft" />
      )}
      {RUN_STATUS_LABEL[status]}
    </Badge>
  );
}

export function ScanStatusBadge({ status }: { status: ScanStatus }) {
  const style =
    status === "clean"
      ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
      : status === "infected"
        ? "bg-rose-500/15 text-rose-300 border-rose-500/30"
        : "bg-raised text-ink-dim border-line-bright";
  return <Badge className={style}>malware: {status}</Badge>;
}

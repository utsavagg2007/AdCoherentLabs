import { Progress } from "@/components/ui/progress";
import type { Quota } from "@/lib/types";

export function QuotaMeter({ quota }: { quota: Quota }) {
  const pct =
    quota.limit == null ? 0 : Math.min(100, (quota.used / quota.limit) * 100);
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-ink-dim">Scans this period</span>
        <span className="font-mono text-ink">
          {quota.used}
          <span className="text-ink-faint">
            {" / "}
            {quota.limit ?? "∞"}
          </span>
        </span>
      </div>
      {quota.limit != null ? (
        <Progress value={pct} />
      ) : (
        <p className="text-[11px] text-ink-faint">Custom quota (enterprise)</p>
      )}
    </div>
  );
}

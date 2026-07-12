import { cn } from "@/lib/utils";
import type { RunStatus } from "@/lib/types";
import { Check, X } from "lucide-react";

const STEPS = [
  { key: "cv", label: "Computer Vision", tag: "L1" },
  { key: "nlp", label: "NLP & Routing", tag: "L2" },
  { key: "llm", label: "LLM Reasoning", tag: "L3" },
  { key: "rules", label: "Rule Engine", tag: "L4" },
  { key: "reconcile", label: "Reconcile", tag: "✓" },
] as const;

// Index of the step a status is working on; STEPS.length = all done.
const STATUS_STEP: Record<RunStatus, number> = {
  queued: -1,
  running_cv: 0,
  running_nlp: 1,
  running_llm: 2,
  running_rules: 3,
  reconciling: 4,
  complete: 5,
  failed: -2,
};

export function LayerPipeline({
  status,
  className,
}: {
  status: RunStatus;
  className?: string;
}) {
  const active = STATUS_STEP[status];
  const failed = status === "failed";

  return (
    <ol className={cn("flex flex-wrap items-center gap-y-3", className)}>
      {STEPS.map((step, i) => {
        const done = !failed && active > i;
        const current = !failed && active === i;
        return (
          <li key={step.key} className="flex items-center">
            <div className="flex items-center gap-2.5">
              <span
                className={cn(
                  "grid size-8 shrink-0 place-items-center rounded-full border text-[11px] font-bold",
                  done &&
                    "border-brand/40 bg-brand/15 text-brand",
                  current &&
                    "border-violet-400/50 bg-violet-500/15 text-violet-300 animate-pulse-soft",
                  failed &&
                    "border-rose-500/40 bg-rose-500/10 text-rose-300",
                  !done && !current && !failed &&
                    "border-line-bright bg-raised text-ink-faint",
                )}
              >
                {done ? <Check size={14} /> : failed ? <X size={14} /> : step.tag}
              </span>
              <div className="min-w-0">
                <p
                  className={cn(
                    "text-xs font-medium leading-tight",
                    done && "text-ink",
                    current && "text-violet-200",
                    !done && !current && "text-ink-faint",
                  )}
                >
                  {step.label}
                </p>
                <p className="text-[10px] text-ink-faint">
                  {done ? "done" : current ? "running…" : failed ? "aborted" : "pending"}
                </p>
              </div>
            </div>
            {i < STEPS.length - 1 && (
              <span
                aria-hidden
                className={cn(
                  "mx-3 h-px w-6 sm:w-10",
                  done ? "bg-brand/40" : "bg-line-bright",
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}

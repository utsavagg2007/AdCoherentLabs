"use client";

/** Loading, empty, and error states — deliberate, never placeholder-y. */

import { useState } from "react";
import { ChevronDown, Loader2, ShieldAlert } from "lucide-react";
import { describeError, isApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export function Spinner({ className }: { className?: string }) {
  return (
    <Loader2
      aria-label="Loading"
      className={cn("size-5 animate-spin text-ink-600", className)}
    />
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-lg bg-zinc-200/70", className)}
    />
  );
}

export function PageLoading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 text-ink-500">
      <Spinner />
      <p className="text-sm font-medium">{label}…</p>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "bg-grid-faint flex flex-col items-center justify-center rounded-2xl border border-dashed border-white/15 px-6 py-14 text-center",
        className
      )}
    >
      {icon && (
        <div className="mb-4 flex size-12 items-center justify-center rounded-2xl border border-white/15 bg-white/6 text-ink-600">
          {icon}
        </div>
      )}
      <h3 className="text-[15px] font-bold text-ink-900">{title}</h3>
      {description && (
        <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-ink-500">
          {description}
        </p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/** Normalized API error panel with a support-friendly request-id detail. */
export function ErrorPanel({
  error,
  onRetry,
  className,
  compact,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { title, detail } = describeError(error);
  const api = isApiError(error) ? error : null;

  return (
    <div
      role="alert"
      className={cn(
        "rounded-2xl border border-red-400/25 bg-red-400/10 p-4",
        compact ? "p-3" : "p-4",
        className
      )}
    >
      <div className="flex items-start gap-3">
        <ShieldAlert className="mt-0.5 size-4.5 shrink-0 text-red-300" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-bold text-red-200">{title}</p>
          <p className="mt-0.5 text-[13px] leading-relaxed text-red-300/90">
            {detail}
          </p>
          {api && (api.requestId || api.code) && (
            <div className="mt-2">
              <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                aria-expanded={open}
                className="inline-flex items-center gap-1 text-[12px] font-semibold text-red-300 hover:text-red-200"
              >
                Support details
                <ChevronDown
                  className={cn("size-3.5 transition-transform", open && "rotate-180")}
                  aria-hidden
                />
              </button>
              {open && (
                <dl className="mt-2 space-y-1 rounded-lg border border-red-400/25 bg-red-400/10 p-2.5 font-mono text-[11px] text-red-200">
                  <div className="flex gap-2">
                    <dt className="font-bold">code</dt>
                    <dd className="break-all">{api.code}</dd>
                  </div>
                  {api.requestId && (
                    <div className="flex gap-2">
                      <dt className="font-bold">request_id</dt>
                      <dd className="break-all select-all">{api.requestId}</dd>
                    </div>
                  )}
                  <div className="flex gap-2">
                    <dt className="font-bold">status</dt>
                    <dd>{api.status}</dd>
                  </div>
                </dl>
              )}
            </div>
          )}
          {onRetry && (
            <div className="mt-3">
              <Button variant="secondary" size="sm" onClick={onRetry}>
                Try again
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** The legal disclaimer that rides on every report surface. */
export function Disclaimer({ className }: { className?: string }) {
  return (
    <p
      className={cn(
        "text-[12px] leading-relaxed text-ink-500 italic",
        className
      )}
    >
      AdCoherent reports are decision support for your compliance process, not
      legal advice.
    </p>
  );
}

"use client";

/** The Claude-style live activity feed: what the engine is doing right now,
 * narrated line by line from GET /v1/runs/{id}/events. The backend only ever
 * emits fixed message templates + aggregate counts, so nothing private can
 * appear here. Incremental polling by last event id; the newest line
 * shimmers while the run is active. */

import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, CheckCircle2, CircleAlert } from "lucide-react";
import { useApi } from "@/components/providers";
import { Spinner } from "@/components/ui/feedback";
import { usePolling, usePrefersReducedMotion } from "@/lib/hooks";
import type { RunEvent, RunEventStage } from "@/lib/types";
import { cn } from "@/lib/utils";

const STAGE_LABEL: Record<RunEventStage, string> = {
  queued: "Queued",
  ingest: "Ingest",
  cv: "Vision",
  nlp: "Language",
  retrieval: "Retrieval",
  llm: "Review",
  rules: "Verify",
  report: "Report",
  done: "Done",
  error: "Error",
};

function DetailChips({ detail }: { detail: Record<string, unknown> }) {
  const frameworks = Array.isArray(detail.frameworks)
    ? (detail.frameworks as string[])
    : null;
  if (!frameworks?.length) return null;
  return (
    <span className="mt-1.5 flex flex-wrap gap-1.5">
      {frameworks.map((f) => (
        <span
          key={f}
          className="rounded border border-line bg-tint px-1.5 py-px font-mono text-[10.5px] font-semibold text-muted"
        >
          {f}
        </span>
      ))}
    </span>
  );
}

export function ActivityFeed({
  runId,
  active,
  terminal,
}: {
  runId: string;
  active: boolean;
  terminal: "complete" | "human_review" | "failed" | null;
}) {
  const api = useApi();
  const reduced = usePrefersReducedMotion();
  const [events, setEvents] = useState<RunEvent[]>([]);
  const lastIdRef = useRef(0);
  const listRef = useRef<HTMLOListElement>(null);
  const stickToBottomRef = useRef(true);
  const tailFetchedRef = useRef(false);

  const pull = useCallback(async () => {
    try {
      const res = await api.runEvents(runId, lastIdRef.current);
      if (res.events.length) {
        lastIdRef.current = res.last_id;
        setEvents((prev) => [...prev, ...res.events]);
      }
    } catch {
      // feed is best-effort; the run page's own polling reports real errors
    }
  }, [api, runId]);

  useEffect(() => {
    const t = setTimeout(() => void pull(), 0);
    return () => clearTimeout(t);
  }, [pull]);

  usePolling(() => void pull(), active ? 2000 : null);

  // one tail fetch when the run stops: pick up report/done events
  useEffect(() => {
    if (active || tailFetchedRef.current) return;
    tailFetchedRef.current = true;
    const t = setTimeout(() => void pull(), 600);
    return () => clearTimeout(t);
  }, [active, pull]);

  // keep the newest line in view unless the user scrolled up
  useEffect(() => {
    const el = listRef.current;
    if (!el || !stickToBottomRef.current) return;
    el.scrollTo({ top: el.scrollHeight, behavior: reduced ? "auto" : "smooth" });
  }, [events.length, reduced]);

  if (!events.length && !active) return null;

  return (
    <section aria-label="Live activity" className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
        <h2 className="flex items-center gap-2 text-[13.5px] font-extrabold text-strong">
          <Activity className="size-4 text-subtle" aria-hidden />
          Live activity
        </h2>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 text-[12px] font-semibold",
            active
              ? "text-muted"
              : terminal === "failed"
                ? "text-fail"
                : "text-pass"
          )}
        >
          {active ? (
            <>
              <Spinner className="size-3.5" />
              Streaming
            </>
          ) : terminal === "failed" ? (
            <>
              <CircleAlert className="size-3.5" aria-hidden />
              Ended
            </>
          ) : (
            <>
              <CheckCircle2 className="size-3.5" aria-hidden />
              Finished
            </>
          )}
        </span>
      </div>

      <ol
        ref={listRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          stickToBottomRef.current =
            el.scrollHeight - el.scrollTop - el.clientHeight < 48;
        }}
        className="max-h-[380px] space-y-0.5 overflow-y-auto scroll-py-2 p-3"
        aria-live="polite"
      >
        {events.length === 0 && (
          <li className="flex items-center gap-2.5 px-2.5 py-2 text-[13px] text-subtle">
            <Spinner className="size-3.5" />
            Waiting for the first update…
          </li>
        )}
        {events.map((e, i) => {
          const latest = active && i === events.length - 1;
          const isError = e.stage === "error";
          return (
            <li
              key={e.id}
              className="flex animate-fade-up items-start gap-3 rounded-xl px-2.5 py-2"
            >
              <span
                className={cn(
                  "mt-0.5 w-[72px] shrink-0 font-mono text-[10.5px] font-bold tracking-wider uppercase",
                  isError ? "text-fail" : "text-subtle"
                )}
              >
                {STAGE_LABEL[e.stage] ?? e.stage}
              </span>
              <span className="min-w-0">
                <span
                  className={cn(
                    "block text-[13.5px] leading-relaxed",
                    latest && !reduced
                      ? "text-shimmer"
                      : isError
                        ? "text-fail"
                        : "text-muted"
                  )}
                >
                  {e.message}
                </span>
                <DetailChips detail={e.detail} />
              </span>
            </li>
          );
        })}
      </ol>

      <p className="border-t border-line px-5 py-2.5 text-[11.5px] leading-relaxed text-subtle">
        Stage names and aggregate counts only — your creative&apos;s content and
        the model&apos;s reasoning never appear in this feed.
      </p>
    </section>
  );
}

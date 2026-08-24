"use client";

/**
 * Everything the engine says about one run, as transcript turns.
 *
 * The questions rendered here are the REAL ones: when the callback loop cannot
 * close a check on the evidence available, the run lands in `human_review` and
 * the report carries the engine's reason and outstanding instructions. Those
 * are what the reply box answers, and the answer goes back as
 * `operator_guidance` on POST /v1/runs/{id}/resume — a linked follow-up run
 * that redoes only the LLM round.
 *
 * No cost is shown anywhere in this file, by product decision. The escrow is
 * still running underneath; it is simply not the user's concern.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  Check,
  CircleAlert,
  RefreshCcw,
  UserRoundSearch,
} from "lucide-react";
import Link from "next/link";
import { ActivityFeed } from "@/components/app/activity-feed";
import { Turn, TurnCard } from "@/components/chat/turn";
import { ReportView } from "@/components/report/report-view";
import { useApi, useOrg } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/feedback";
import { isApiError } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { RUN_STAGES, runStageIndex } from "@/lib/labels";
import {
  ACTIVE_RUN_STATUSES,
  type ReportResponse,
  type RunDetail,
  type RunResponse,
} from "@/lib/types";
import { cn } from "@/lib/utils";

export function RunThread({
  runId,
  onResumed,
}: {
  runId: string;
  /** A resume creates a NEW run; the page appends it to the transcript. */
  onResumed: (newRunId: string) => void;
}) {
  const api = useApi();
  const { role } = useOrg();

  const [resp, setResp] = useState<RunResponse | null>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const inFlight = useRef(false);

  const status = resp?.run.status ?? null;
  const isActive =
    status !== null && (ACTIVE_RUN_STATUSES as string[]).includes(status);
  const hasReport = status === "complete" || status === "human_review";

  const load = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const rr = await api.getRun(runId);
      setResp(rr);
      setError(null);
      if (rr.run.status === "complete" || rr.run.status === "human_review") {
        try {
          setReport(await api.getReport(runId));
        } catch (e) {
          // 409 is the documented "not assembled yet" state, not a failure.
          if (!isApiError(e) || e.status !== 409) throw e;
        }
      }
    } catch (e) {
      setError(e);
    } finally {
      inFlight.current = false;
    }
  }, [api, runId]);

  useEffect(() => {
    // Scheduled, not called inline: Next 16's react-hooks lint rejects a
    // synchronous setState in an effect body. Same pattern as runs/[id].
    const t = setTimeout(() => void load(), 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  usePolling(() => void load(), isActive || resp === null ? 3000 : null);

  const startedAt = resp?.run.created_at ?? new Date().toISOString();

  if (error && !resp) {
    return (
      <Turn role="assistant" at={new Date()}>
        <p>I couldn&apos;t load this review.</p>
        <TurnCard tone="warn">
          <Button size="sm" variant="secondary" onClick={() => void load()}>
            <RefreshCcw className="size-4" aria-hidden />
            Try again
          </Button>
        </TurnCard>
      </Turn>
    );
  }

  return (
    <>
      {/* ---- working ---- */}
      {(resp === null || isActive) && (
        <Turn role="assistant" at={startedAt} working label="AdCoherent · working">
          <p>
            Running the four-layer review — evidence, claims, regulation, then
            deterministic verification.
          </p>
          <StageRail status={status} />
          <div className="mt-3">
            <ActivityFeed runId={runId} active terminal={null} />
          </div>
        </Turn>
      )}

      {/* ---- the engine has a question ---- */}
      {status === "human_review" && (
        <HumanReviewTurn
          runId={runId}
          at={resp?.run.finished_at ?? startedAt}
          run={resp!.run}
          report={report}
          canResume={role !== "viewer"}
          onResumed={onResumed}
        />
      )}

      {/* ---- done ---- */}
      {status === "complete" && (
        <Turn role="assistant" at={resp?.run.finished_at ?? startedAt}>
          <p className="flex items-center gap-2 font-semibold text-strong">
            <Check className="size-4 text-pass" aria-hidden />
            Review complete.
          </p>
          {report ? (
            <div className="mt-4">
              <ReportView
                runId={runId}
                run={resp!.run}
                report={report.report}
                disclaimer={report.disclaimer}
              />
            </div>
          ) : (
            <p className="mt-2 flex items-center gap-2 text-subtle">
              <Spinner className="size-4" /> Assembling the report…
            </p>
          )}
        </Turn>
      )}

      {/* ---- failed ---- */}
      {status === "failed" && (
        <Turn role="assistant" at={resp?.run.finished_at ?? startedAt}>
          <p className="flex items-center gap-2 font-semibold text-strong">
            <CircleAlert className="size-4 text-fail" aria-hidden />
            This review didn&apos;t finish.
          </p>
          <TurnCard tone="warn">
            <p className="text-[13.5px] leading-relaxed text-warn">
              {resp?.run.error?.startsWith("rejected:")
                ? "Your plan didn't have enough review capacity left, so nothing was analysed."
                : "Something went wrong while processing this creative. Sending it again is safe."}
            </p>
            {(resp?.run.error || resp?.queue?.last_error) && (
              <details className="mt-3">
                <summary className="cursor-pointer text-[12.5px] font-bold text-subtle hover:text-strong">
                  Technical details
                </summary>
                <div className="mt-2 space-y-1 rounded-lg border border-line bg-surface p-3 font-mono text-[11.5px] break-words text-muted">
                  {resp?.run.error && <p>error: {resp.run.error}</p>}
                  {resp?.queue?.last_error && (
                    <p>queue: {resp.queue.last_error}</p>
                  )}
                  <p>run_id: {runId}</p>
                </div>
              </details>
            )}
            {resp?.run.error?.startsWith("rejected:") && (
              <div className="mt-4">
                <Button size="sm" href="/billing">
                  Review your plan
                  <ArrowUpRight className="size-4" aria-hidden />
                </Button>
              </div>
            )}
          </TurnCard>
        </Turn>
      )}

      {/* Deep link out, for anyone who wants the standalone record. */}
      {hasReport && (
        <p className="grid grid-cols-[3rem_minmax(0,1fr)] sm:grid-cols-[6rem_minmax(0,1fr)]">
          <span className="border-r border-line" aria-hidden />
          <span className="pb-6 pl-4 text-[12px] text-subtle sm:pl-6">
            <Link
              href={`/runs/${runId}`}
              className="font-semibold underline underline-offset-2 hover:text-strong"
            >
              Open this run on its own page
            </Link>{" "}
            · run {runId.slice(0, 8)}
          </span>
        </p>
      )}
    </>
  );
}

function StageRail({ status }: { status: string | null }) {
  const idx = status ? runStageIndex(status as never) : 0;
  return (
    <ol className="mt-3 flex flex-wrap items-center gap-x-1 gap-y-2">
      {RUN_STAGES.map((stage, i) => {
        const state = i < idx ? "done" : i === idx ? "now" : "todo";
        return (
          <li key={stage.status} className="flex items-center gap-1">
            <span
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px] font-bold whitespace-nowrap",
                state === "done" && "border-pass-line bg-pass-soft text-pass",
                state === "now" && "border-brand-line bg-brand-soft text-brand-text",
                state === "todo" && "border-line bg-transparent text-subtle"
              )}
            >
              {state === "done" && <Check className="size-3" aria-hidden />}
              {state === "now" && (
                <span className="size-1.5 animate-pulse-dot rounded-full bg-brand" />
              )}
              {stage.label}
            </span>
            {i < RUN_STAGES.length - 1 && (
              <span
                aria-hidden
                className={cn(
                  "h-px w-3",
                  state === "done" ? "bg-pass-solid/40" : "bg-tint-3"
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function HumanReviewTurn({
  runId,
  at,
  run,
  report,
  canResume,
  onResumed,
}: {
  runId: string;
  at: string;
  run: RunDetail;
  report: ReportResponse | null;
  canResume: boolean;
  onResumed: (newRunId: string) => void;
}) {
  const api = useApi();
  const [guidance, setGuidance] = useState("");
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  const hr = report?.report.human_review;
  const instructions = hr?.instructions ?? [];

  async function resume() {
    if (!guidance.trim() || sending) return;
    setSending(true);
    setFailed(null);
    try {
      const res = await api.resumeRun(runId, guidance.trim());
      onResumed(res.run_id);
    } catch (e) {
      setSending(false);
      setFailed(isApiError(e) ? e.message : "Try again in a moment.");
    }
  }

  return (
    <Turn role="assistant" at={at} label="AdCoherent · needs you">
      <p className="flex items-center gap-2 font-semibold text-strong">
        <UserRoundSearch className="size-4 text-warn" aria-hidden />
        I need something from you before I can close this out.
      </p>

      {hr?.reason && (
        <p className="mt-2 leading-relaxed">{hr.reason}</p>
      )}

      {instructions.length > 0 && (
        <ul className="mt-3 space-y-2">
          {instructions.map((ins, i) => (
            <li
              key={i}
              className="rounded-lg border border-warn-line bg-warn-soft p-3 text-[13px] leading-relaxed text-warn"
            >
              {ins.check_id && (
                <span className="mr-1.5 font-mono text-[11px] font-bold">
                  {String(ins.check_id)}
                </span>
              )}
              {String(ins.instruction ?? ins.message ?? "")}
            </li>
          ))}
        </ul>
      )}

      {!report && (
        <p className="mt-2 flex items-center gap-2 text-subtle">
          <Spinner className="size-4" /> Loading what it stopped on…
        </p>
      )}

      {canResume ? (
        <TurnCard tone="asking">
          <label htmlFor="guidance" className="label text-brand-text">
            Your answer
          </label>
          <textarea
            id="guidance"
            className="input min-h-28 resize-y bg-surface leading-relaxed"
            placeholder="The APR disclosure is in the footer of the landing page the ad links to — attached as Exhibit B in our rate sheet."
            value={guidance}
            onChange={(e) => setGuidance(e.target.value)}
            maxLength={20_000}
            disabled={sending}
          />
          {failed && (
            <p role="alert" className="mt-2 text-[12.5px] font-semibold text-fail">
              {failed}
            </p>
          )}
          <div className="mt-4">
            <Button size="sm" onClick={resume} loading={sending} disabled={!guidance.trim()}>
              Send and re-review
            </Button>
          </div>
          <p className="mt-2 text-[12px] leading-relaxed text-subtle">
            Only the review round runs again — the creative isn&apos;t
            re-processed.
          </p>
        </TurnCard>
      ) : (
        <TurnCard>
          <p className="text-[13px] text-subtle">
            A reviewer, admin, or owner on your team can answer this and resume
            the review.
          </p>
        </TurnCard>
      )}

      {report && (
        <div className="mt-5">
          <ReportView
            runId={runId}
            run={run}
            report={report.report}
            disclaimer={report.disclaimer}
          />
        </div>
      )}
    </Turn>
  );
}

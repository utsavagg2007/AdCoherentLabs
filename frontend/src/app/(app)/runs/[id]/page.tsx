"use client";

/** Run tracking + report. Polls while active (Realtime assists when the
 * stack has it enabled), treats /report 409 as the expected not-ready state,
 * and never pretends a report exists early. */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CircleAlert,
  Clock3,
  RefreshCcw,
  UserRoundSearch,
} from "lucide-react";
import { ActivityFeed } from "@/components/app/activity-feed";
import { PageBody, PageHeader } from "@/components/app/page-header";
import { ReportView } from "@/components/report/report-view";
import { useApi, useOrg } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { RunStatusBadge } from "@/components/ui/badge";
import {
  Disclaimer,
  ErrorPanel,
  PageLoading,
  Spinner,
} from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import { isApiError } from "@/lib/api";
import { usePolling } from "@/lib/hooks";
import { RUN_STAGES, runStageIndex } from "@/lib/labels";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";
import {
  ACTIVE_RUN_STATUSES,
  type ReportResponse,
  type RunResponse,
} from "@/lib/types";
import { cn, formatDateTime } from "@/lib/utils";

export default function RunPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { orgId } = useOrg();
  // keyed remount fully resets run state when the route or org changes
  return <RunView key={`${orgId}|${id}`} id={id} />;
}

function RunView({ id }: { id: string }) {
  const api = useApi();
  const { role } = useOrg();
  const router = useRouter();
  const { toast } = useToast();

  const [runResp, setRunResp] = useState<RunResponse | null>(null);
  const [runError, setRunError] = useState<unknown>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [reportPending, setReportPending] = useState(false);
  const [guidance, setGuidance] = useState("");
  const [resuming, setResuming] = useState(false);
  const loadingRef = useRef(false);

  const status = runResp?.run.status ?? null;
  const isActive =
    status !== null && (ACTIVE_RUN_STATUSES as string[]).includes(status);
  const isTerminalWithReport = status === "complete" || status === "human_review";

  // -- data loading ---------------------------------------------------------
  const load = async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      const rr = await api.getRun(id);
      setRunResp(rr);
      setRunError(null);
      const st = rr.run.status;
      if ((st === "complete" || st === "human_review") && !report) {
        try {
          setReport(await api.getReport(id));
          setReportPending(false);
        } catch (e) {
          if (isApiError(e) && e.status === 409) {
            // expected: worker hasn't persisted the report yet
            setReportPending(true);
          } else if (isApiError(e) && e.status === 404) {
            setReportPending(true);
          } else {
            setRunError(e);
          }
        }
      }
    } catch (e) {
      setRunError(e);
    } finally {
      loadingRef.current = false;
    }
  };

  useEffect(() => {
    // scheduled, not called inline — initial load happens off the effect body
    const t = setTimeout(() => void load(), 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // poll while the run is active (or the report is still materializing)
  usePolling(
    () => void load(),
    isActive || (isTerminalWithReport && !report) || (!runResp && !runError)
      ? 3500
      : null
  );

  // realtime assist — polling remains the reliable fallback
  useEffect(() => {
    if (!supabaseConfigured() || !isActive) return;
    try {
      const channel = getSupabase()
        .channel(`run-${id}`)
        .on(
          "postgres_changes",
          {
            event: "UPDATE",
            schema: "public",
            table: "analysis_runs",
            filter: `id=eq.${id}`,
          },
          () => void load()
        )
        .on(
          "postgres_changes",
          {
            event: "INSERT",
            schema: "public",
            table: "findings",
            filter: `run_id=eq.${id}`,
          },
          () => void load()
        )
        .subscribe();
      return () => {
        void getSupabase().removeChannel(channel);
      };
    } catch {
      return; // realtime unavailable — polling covers it
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, isActive]);

  // -- resume (human review) ------------------------------------------------
  async function resume() {
    if (!guidance.trim()) return;
    setResuming(true);
    try {
      const res = await api.resumeRun(id, guidance.trim());
      toast({
        kind: "success",
        title: "Review resumed at no additional cost",
        detail: "The linked follow-up run is queued with your guidance.",
      });
      router.push(`/runs/${res.run_id}`);
    } catch (e) {
      setResuming(false);
      toast({
        kind: "error",
        title: "Couldn't resume the run",
        detail: isApiError(e) ? e.message : "Try again in a moment.",
      });
    }
  }

  // -- render ---------------------------------------------------------------
  if (!runResp && !runError) {
    return (
      <>
        <PageHeader title="Review run" />
        <PageBody>
          <PageLoading label="Loading run" />
        </PageBody>
      </>
    );
  }

  if (runError && !runResp) {
    return (
      <>
        <PageHeader title="Review run" />
        <PageBody>
          <ErrorPanel error={runError} onRetry={() => void load()} />
        </PageBody>
      </>
    );
  }

  const run = runResp!.run;
  const stageIdx = runStageIndex(run.status);

  return (
    <>
      <PageHeader
        title={`Run ${run.id.slice(0, 8)}`}
        description={`Submitted ${formatDateTime(run.created_at)}${run.tier ? ` · ${run.tier} tier` : ""}${run.model_id ? ` · ${run.model_id}` : ""}`}
        actions={
          <div className="flex items-center gap-2.5">
            <RunStatusBadge status={run.status} />
            <Button
              variant="secondary"
              size="sm"
              href={`/submissions/${run.submission_id}`}
            >
              Submission
            </Button>
          </div>
        }
      />
      <PageBody>
        <div className="space-y-6">
          {run.resumed_from_run_id && (
            <div className="flex items-center gap-2.5 rounded-xl border border-white/15 bg-white/6 px-4 py-3 text-[13px] text-ink-950">
              <UserRoundSearch className="size-4 shrink-0" aria-hidden />
              <p>
                Resumed with reviewer guidance from{" "}
                <Link
                  href={`/runs/${run.resumed_from_run_id}`}
                  className="font-bold underline underline-offset-2"
                >
                  run {run.resumed_from_run_id.slice(0, 8)}
                </Link>{" "}
                — charged 0 credits.
              </p>
            </div>
          )}

          {/* ---------------- active: stage strip ---------------- */}
          {isActive && (
            <section
              aria-label="Review progress"
              className="card overflow-hidden"
            >
              <div className="border-b border-line px-5 py-4">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="flex items-center gap-2.5 text-[15px] font-extrabold text-ink-900">
                    <Spinner className="size-4" />
                    Review in progress
                  </h2>
                  <p className="text-[12px] text-ink-500">
                    Updates automatically
                  </p>
                </div>
              </div>
              <ol className="flex flex-wrap items-center gap-x-1 gap-y-2 px-5 py-4">
                {RUN_STAGES.map((stage, i) => {
                  const state =
                    i < stageIdx ? "done" : i === stageIdx ? "now" : "todo";
                  return (
                    <li key={stage.status} className="flex items-center gap-1">
                      <span
                        className={cn(
                          "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px] font-bold whitespace-nowrap",
                          state === "done" &&
                            "border-emerald-400/25 bg-emerald-400/10 text-emerald-300",
                          state === "now" &&
                            "border-white/25 bg-white/10 text-ink-950",
                          state === "todo" &&
                            "border-white/10 bg-transparent text-ink-500"
                        )}
                      >
                        {state === "done" && (
                          <Check className="size-3" aria-hidden />
                        )}
                        {state === "now" && (
                          <span className="size-1.5 animate-pulse-dot rounded-full bg-white" />
                        )}
                        {stage.label}
                      </span>
                      {i < RUN_STAGES.length - 1 && (
                        <span
                          aria-hidden
                          className={cn(
                            "h-px w-3",
                            state === "done" ? "bg-emerald-400/40" : "bg-white/12"
                          )}
                        />
                      )}
                    </li>
                  );
                })}
              </ol>
              {runResp!.queue?.attempts != null && runResp!.queue.attempts > 1 && (
                <p className="border-t border-line px-5 py-3 text-[12px] text-ink-500">
                  <Clock3 className="mr-1 inline size-3.5 align-[-2px]" aria-hidden />
                  Attempt {runResp!.queue.attempts} — transient issues retry
                  automatically.
                </p>
              )}
            </section>
          )}

          {/* ---------------- live activity feed ---------------- */}
          <ActivityFeed
            runId={id}
            active={isActive}
            terminal={
              status === "complete" ||
              status === "human_review" ||
              status === "failed"
                ? status
                : null
            }
          />

          {/* ---------------- failed ---------------- */}
          {status === "failed" && (
            <section aria-label="Run failed" className="card overflow-hidden">
              <div className="flex items-start gap-4 p-6">
                <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl border border-red-400/25 bg-red-400/10 text-red-300">
                  <CircleAlert className="size-5" aria-hidden />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="text-lg font-extrabold text-ink-900">
                    This review didn&apos;t finish
                  </h2>
                  <p className="mt-1.5 max-w-xl text-sm leading-relaxed text-ink-600">
                    {run.error?.startsWith("rejected:")
                      ? "The run was rejected because the credit balance couldn't cover it. Nothing was analyzed."
                      : "Something went wrong while processing this creative. If credits were charged for a failure on our side, they're refunded automatically. Submitting again is safe."}
                  </p>
                  {(run.error || runResp!.queue?.last_error) && (
                    <details className="mt-3">
                      <summary className="cursor-pointer text-[12.5px] font-bold text-ink-500 hover:text-ink-900">
                        Technical details
                      </summary>
                      <div className="mt-2 space-y-1.5 rounded-lg border border-line bg-cream p-3 font-mono text-[11.5px] break-words text-ink-600">
                        {run.error && <p>error: {run.error}</p>}
                        {runResp!.queue?.last_error && (
                          <p>queue: {runResp!.queue.last_error}</p>
                        )}
                        {runResp!.queue?.attempts != null && (
                          <p>attempts: {runResp!.queue.attempts}</p>
                        )}
                        <p>run_id: {run.id}</p>
                      </div>
                    </details>
                  )}
                  <div className="mt-5 flex flex-wrap gap-2.5">
                    <Button href="/submissions/new">
                      <RefreshCcw className="size-4" aria-hidden />
                      Start a new review
                    </Button>
                    <Button variant="secondary" href="/reports">
                      <ArrowLeft className="size-4" aria-hidden />
                      Run history
                    </Button>
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* ---------------- human review ---------------- */}
          {status === "human_review" && (
            <section
              aria-label="Human review requested"
              className="overflow-hidden rounded-2xl border border-amber-400/30 bg-coal-800 shadow-(--shadow-soft)"
            >
              <div className="border-b border-amber-400/25 bg-amber-400/10 px-6 py-4">
                <h2 className="flex items-center gap-2.5 text-[16px] font-extrabold text-amber-200">
                  <UserRoundSearch className="size-4.5" aria-hidden />
                  This run is waiting on your review team
                </h2>
                <p className="mt-1 text-[13px] leading-relaxed text-amber-200/80">
                  The automated loop used its callback budget without
                  converging. Add guidance below and resume — the follow-up run
                  is linked to this one and charges{" "}
                  <strong>zero additional credits</strong>.
                </p>
              </div>
              <div className="space-y-4 p-6">
                {report?.report.human_review ? (
                  <div className="space-y-3">
                    {report.report.human_review.reason && (
                      <div>
                        <p className="text-[11px] font-bold tracking-wider text-ink-500 uppercase">
                          Why it stopped
                        </p>
                        <p className="mt-1 text-sm leading-relaxed text-ink-800">
                          {report.report.human_review.reason}
                        </p>
                      </div>
                    )}
                    {(report.report.human_review.instructions?.length ?? 0) > 0 && (
                      <div>
                        <p className="text-[11px] font-bold tracking-wider text-ink-500 uppercase">
                          Outstanding instructions
                        </p>
                        <ul className="mt-1.5 space-y-1.5">
                          {report.report.human_review.instructions!.map((ins, i) => (
                            <li
                              key={i}
                              className="rounded-lg border border-amber-400/25 bg-amber-400/10 p-3 text-[13px] leading-relaxed text-amber-200"
                            >
                              {ins.check_id && (
                                <span className="mr-1.5 font-mono text-[11px] font-bold text-amber-300">
                                  {String(ins.check_id)}
                                </span>
                              )}
                              {String(ins.instruction ?? ins.message ?? "")}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {report.report.human_review.how_to_resume && (
                      <p className="text-[12.5px] leading-relaxed text-ink-500">
                        {report.report.human_review.how_to_resume}
                      </p>
                    )}
                  </div>
                ) : reportPending ? (
                  <p className="flex items-center gap-2 text-sm text-ink-500">
                    <Spinner className="size-4" /> Loading the review context…
                  </p>
                ) : null}

                {role === "viewer" ? (
                  <p className="rounded-xl bg-cream p-3.5 text-[13px] text-ink-500">
                    A reviewer, admin, or owner can add guidance and resume this
                    run.
                  </p>
                ) : (
                  <div>
                    <label htmlFor="guidance" className="label">
                      Reviewer guidance
                    </label>
                    <textarea
                      id="guidance"
                      className="input min-h-28 resize-y leading-relaxed"
                      placeholder="e.g. Treat the asterisked footnote as the APR disclosure; evaluate prominence against the headline claim…"
                      value={guidance}
                      onChange={(e) => setGuidance(e.target.value)}
                      maxLength={20000}
                    />
                    <div className="mt-3 flex items-center justify-between gap-3">
                      <p className="text-[12px] text-ink-500">
                        Sent to the model alongside the original creative
                        evidence.
                      </p>
                      <Button
                        onClick={resume}
                        loading={resuming}
                        disabled={!guidance.trim()}
                      >
                        Resume run · 0 credits
                        <ArrowRight className="size-4" aria-hidden />
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </section>
          )}

          {/* ---------------- report ---------------- */}
          {isTerminalWithReport &&
            (report ? (
              <ReportView
                runId={run.id}
                run={run}
                report={report.report}
                disclaimer={report.disclaimer}
              />
            ) : reportPending ? (
              <section className="card flex items-center gap-3 p-6 text-sm text-ink-500">
                <Spinner className="size-4" />
                The run finished — assembling the report…
              </section>
            ) : null)}

          <Disclaimer />
        </div>
      </PageBody>
    </>
  );
}

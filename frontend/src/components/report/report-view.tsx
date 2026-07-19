"use client";

/** The auditable report — findings with evidence, deterministic verification,
 * audit rounds, and provenance. Renders only what the payload contains. */

import { useMemo, useState } from "react";
import {
  BadgeCheck,
  CheckCheck,
  ChevronDown,
  CircleAlert,
  Download,
  FileWarning,
  Fingerprint,
  Flag,
  Info,
  Quote,
  ShieldCheck,
  ThumbsUp,
  Trash2,
  Wrench,
} from "lucide-react";
import { CreativePanel } from "./creative-panel";
import { useApi, useOrg } from "@/components/providers";
import {
  Chip,
  FindingStatusBadge,
  SeverityBadge,
  VerdictBadge,
} from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { isApiError } from "@/lib/api";
import { useAsyncData } from "@/lib/hooks";
import { SEVERITY_ORDER, frameworkLabel } from "@/lib/labels";
import type {
  EngineReport,
  FailedCheck,
  FindingRow,
  FindingStatus,
  LlmFinding,
  RunDetail,
  Severity,
} from "@/lib/types";
import { cn, formatDateTime, formatDuration, formatNumber } from "@/lib/utils";

// ---------------------------------------------------------------- helpers

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function Collapsible({
  summary,
  children,
  defaultOpen,
}: {
  summary: React.ReactNode;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(Boolean(defaultOpen));
  return (
    <div className="rounded-xl border border-line bg-white">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <span className="min-w-0 flex-1">{summary}</span>
        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-zinc-400 transition-transform",
            open && "rotate-180"
          )}
          aria-hidden
        />
      </button>
      {open && <div className="border-t border-line px-4 py-3.5">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- finding card

function FindingCard({
  finding,
  index,
  dbRow,
  canReview,
  onReview,
  busy,
}: {
  finding: LlmFinding;
  index: number;
  dbRow: FindingRow | null;
  canReview: boolean;
  onReview: (row: FindingRow, status: Exclude<FindingStatus, "open">) => void;
  busy: string | null;
}) {
  return (
    <article
      className="card p-4"
      aria-label={`Finding ${index + 1}: ${finding.framework ?? "unknown framework"}`}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-mono text-[11px] font-bold text-zinc-400">
          F{index + 1}
        </span>
        {finding.severity && <SeverityBadge severity={finding.severity} />}
        {finding.verdict && <VerdictBadge verdict={finding.verdict} />}
        <span className="text-[12px] font-bold text-zinc-500">
          {frameworkLabel(finding.framework)}
        </span>
        {dbRow && dbRow.status !== "open" && (
          <span className="ml-auto">
            <FindingStatusBadge status={dbRow.status} />
          </span>
        )}
      </div>

      {finding.quoted_evidence && (
        <blockquote className="mt-3 flex gap-2.5 rounded-lg border-l-2 border-violet-400 bg-violet-50/60 p-3">
          <Quote className="mt-0.5 size-3.5 shrink-0 text-violet-400" aria-hidden />
          <p className="text-[13px] leading-relaxed text-ink-800 italic">
            “{finding.quoted_evidence}”
          </p>
        </blockquote>
      )}

      {finding.reasoning && (
        <p className="mt-3 text-[13.5px] leading-relaxed text-zinc-600">
          {finding.reasoning}
        </p>
      )}

      {(finding.regulation_citations?.length ?? 0) > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {finding.regulation_citations!.map((c) => (
            <Chip key={c}>{c}</Chip>
          ))}
        </div>
      )}

      {finding.scope_of_improvement && (
        <div className="mt-3 flex items-start gap-2.5 rounded-lg bg-cream p-3">
          <Wrench className="mt-0.5 size-3.5 shrink-0 text-zinc-400" aria-hidden />
          <div>
            <p className="text-[11px] font-bold tracking-wider text-zinc-400 uppercase">
              Remediation
            </p>
            <p className="mt-0.5 text-[13px] leading-relaxed text-zinc-700">
              {finding.scope_of_improvement}
            </p>
          </div>
        </div>
      )}

      {((finding.cited_segment_ids?.length ?? 0) > 0 ||
        (finding.cited_entity_ids?.length ?? 0) > 0) && (
        <p className="mt-2.5 font-mono text-[10.5px] text-zinc-400">
          cites{" "}
          {[...(finding.cited_segment_ids ?? []), ...(finding.cited_entity_ids ?? [])].join(
            " · "
          )}
        </p>
      )}

      {dbRow && canReview && (
        <div className="mt-3.5 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <span className="mr-1 text-[11px] font-bold tracking-wider text-zinc-400 uppercase">
            Workflow
          </span>
          <Button
            variant={dbRow.status === "approved" ? "primary" : "secondary"}
            size="sm"
            loading={busy === `${dbRow.id}:approved`}
            disabled={busy !== null && busy !== `${dbRow.id}:approved`}
            onClick={() => onReview(dbRow, "approved")}
          >
            <ThumbsUp className="size-3.5" aria-hidden />
            Approve
          </Button>
          <Button
            variant="secondary"
            size="sm"
            loading={busy === `${dbRow.id}:flagged`}
            disabled={busy !== null && busy !== `${dbRow.id}:flagged`}
            onClick={() => onReview(dbRow, "flagged")}
            className={cn(
              dbRow.status === "flagged" && "!border-amber-300 !bg-amber-50 !text-amber-900"
            )}
          >
            <Flag className="size-3.5" aria-hidden />
            Flag
          </Button>
          <Button
            variant="secondary"
            size="sm"
            loading={busy === `${dbRow.id}:dismissed`}
            disabled={busy !== null && busy !== `${dbRow.id}:dismissed`}
            onClick={() => onReview(dbRow, "dismissed")}
            className={cn(dbRow.status === "dismissed" && "!text-zinc-400")}
          >
            <Trash2 className="size-3.5" aria-hidden />
            Dismiss
          </Button>
        </div>
      )}
    </article>
  );
}

// ---------------------------------------------------------------- main view

export function ReportView({
  runId,
  run,
  report,
  disclaimer,
}: {
  runId: string;
  run: RunDetail;
  report: EngineReport;
  disclaimer: string;
}) {
  const api = useApi();
  const { orgId, role } = useOrg();
  const { toast } = useToast();
  const [busy, setBusy] = useState<string | null>(null);

  const dbFindings = useAsyncData(
    (s) => api.listFindings({ run_id: runId, limit: 500 }, s),
    [api, orgId, runId]
  );

  const canReview = role !== null && role !== "viewer";

  const llmFindings = useMemo(
    () => report.llm_review?.findings ?? [],
    [report.llm_review]
  );
  const verification = report.verification ?? null;
  const defects = verification?.asset_defects ?? [];
  const advisories = verification?.advisories ?? [];

  const grouped = useMemo(() => {
    const out: { severity: Severity; items: { f: LlmFinding; i: number }[] }[] = [];
    for (const severity of SEVERITY_ORDER) {
      const items = llmFindings
        .map((f, i) => ({ f, i }))
        .filter(({ f }) => f.severity === severity);
      if (items.length) out.push({ severity, items });
    }
    const unknown = llmFindings
      .map((f, i) => ({ f, i }))
      .filter(({ f }) => !SEVERITY_ORDER.includes(f.severity as Severity));
    if (unknown.length) out.push({ severity: "low", items: unknown });
    return out;
  }, [llmFindings]);

  const dbByFindingId = useMemo(() => {
    const map = new Map<string, FindingRow>();
    for (const row of dbFindings.data?.findings ?? []) {
      const fid = row.location?.finding_id;
      if (typeof fid === "string") map.set(fid, row);
    }
    return map;
  }, [dbFindings.data]);

  const dbDefectRows = useMemo(
    () =>
      (dbFindings.data?.findings ?? []).filter(
        (r) => r.location?.source === "rule_engine_asset_defect"
      ),
    [dbFindings.data]
  );

  async function review(row: FindingRow, status: Exclude<FindingStatus, "open">) {
    setBusy(`${row.id}:${status}`);
    try {
      await api.reviewFinding(row.id, status);
      dbFindings.refresh({ silent: true });
      toast({ kind: "success", title: `Finding ${status}` });
    } catch (e) {
      toast({
        kind: "error",
        title: "Couldn't update the finding",
        detail: isApiError(e) ? e.message : undefined,
      });
    } finally {
      setBusy(null);
    }
  }

  const potentialViolations = llmFindings.filter(
    (f) => f.verdict === "potential_violation"
  ).length;
  const needsReviewCount = llmFindings.filter(
    (f) => f.verdict === "needs_review"
  ).length;

  const banner =
    report.status === "llm_error"
      ? {
          tone: "border-red-200 bg-red-50",
          icon: <CircleAlert className="size-5 text-red-600" aria-hidden />,
          title: "The review could not be completed",
          text: report.llm_error ?? "The language-model provider failed.",
        }
      : report.status === "human_review"
        ? {
            tone: "border-amber-200 bg-amber-50",
            icon: <FileWarning className="size-5 text-amber-600" aria-hidden />,
            title: "Interim report — awaiting human review",
            text: "Findings below reflect the latest round; resume the run above to finish.",
          }
        : potentialViolations + defects.length > 0
          ? {
              tone: "border-violet-200 bg-violet-50",
              icon: <ShieldCheck className="size-5 text-violet-600" aria-hidden />,
              title: `Review verified — ${potentialViolations + defects.length} item${potentialViolations + defects.length === 1 ? "" : "s"} need attention`,
              text: "The deterministic layer verified this review's soundness. Work the findings below.",
            }
          : {
              tone: "border-emerald-200 bg-emerald-50",
              icon: <BadgeCheck className="size-5 text-emerald-600" aria-hidden />,
              title: "Review verified — no potential violations surfaced",
              text: "Evaluated claims and disclosures came back clear or compliant.",
            };

  return (
    <div className="space-y-6">
      {/* status banner + export */}
      <section
        aria-label="Review outcome"
        className={cn("flex flex-wrap items-center gap-4 rounded-2xl border p-5", banner.tone)}
      >
        <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-white shadow-(--shadow-soft)">
          {banner.icon}
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-[16px] font-extrabold text-ink-900">{banner.title}</h2>
          <p className="mt-0.5 text-[13px] leading-relaxed text-zinc-600">
            {banner.text}
          </p>
        </div>
        <div className="flex items-center gap-4">
          <dl className="hidden items-center gap-4 text-center sm:flex">
            <div>
              <dt className="text-[10.5px] font-bold tracking-wider text-zinc-400 uppercase">
                Findings
              </dt>
              <dd className="text-lg font-extrabold text-ink-900 tabular-nums">
                {llmFindings.length}
              </dd>
            </div>
            <div>
              <dt className="text-[10.5px] font-bold tracking-wider text-zinc-400 uppercase">
                Checks
              </dt>
              <dd className="text-lg font-extrabold text-ink-900 tabular-nums">
                {verification?.checks_run ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-[10.5px] font-bold tracking-wider text-zinc-400 uppercase">
                Rounds
              </dt>
              <dd className="text-lg font-extrabold text-ink-900 tabular-nums">
                {report.llm_rounds_used ?? "—"}/{report.max_llm_rounds ?? "—"}
              </dd>
            </div>
          </dl>
          <Button
            variant="secondary"
            size="sm"
            onClick={() =>
              downloadJson(`adcoherent-report-${runId.slice(0, 8)}.json`, {
                report,
                disclaimer,
              })
            }
          >
            <Download className="size-3.5" aria-hidden />
            JSON
          </Button>
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[360px_1fr]">
        {/* creative */}
        <div className="min-w-0 xl:sticky xl:top-6 xl:self-start">
          <CreativePanel
            submissionId={run.submission_id}
            findings={dbFindings.data?.findings ?? []}
          />
        </div>

        {/* findings column */}
        <div className="min-w-0 space-y-6">
          {llmFindings.length === 0 ? (
            <section className="card p-6 text-center">
              <BadgeCheck className="mx-auto size-7 text-emerald-500" aria-hidden />
              <p className="mt-2 text-[15px] font-bold text-ink-900">
                No findings from the grounded review
              </p>
              <p className="mx-auto mt-1 max-w-sm text-[13px] text-zinc-500">
                The review evaluated the creative against the applicable
                frameworks and raised nothing to work.
              </p>
            </section>
          ) : (
            grouped.map((group) => (
              <section key={group.severity} aria-label={`${group.severity} severity findings`}>
                <div className="mb-3 flex items-center gap-2.5">
                  <SeverityBadge severity={group.severity} />
                  <span className="text-[12px] font-bold text-zinc-400">
                    {group.items.length} finding{group.items.length === 1 ? "" : "s"}
                  </span>
                  {needsReviewCount > 0 && group === grouped[0] && (
                    <span className="ml-auto text-[11.5px] text-zinc-400">
                      {needsReviewCount} marked needs-review
                    </span>
                  )}
                </div>
                <div className="space-y-4">
                  {group.items.map(({ f, i }) => (
                    <FindingCard
                      key={f.finding_id ?? i}
                      finding={f}
                      index={i}
                      dbRow={
                        f.finding_id ? (dbByFindingId.get(f.finding_id) ?? null) : null
                      }
                      canReview={canReview}
                      onReview={review}
                      busy={busy}
                    />
                  ))}
                </div>
              </section>
            ))
          )}

          {/* asset defects */}
          {defects.length > 0 && (
            <section aria-label="Asset defects">
              <h3 className="mb-3 flex items-center gap-2 text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
                <FileWarning className="size-4 text-amber-600" aria-hidden />
                Asset defects · {defects.length}
              </h3>
              <p className="mb-3 -mt-1.5 text-[12.5px] leading-relaxed text-zinc-500">
                Deterministic facts about the creative itself — re-reviewing
                won&apos;t change them; fixing the creative will.
              </p>
              <div className="space-y-3">
                {defects.map((d: FailedCheck, i) => {
                  const dbRow =
                    dbDefectRows.find((r) => r.rule_ref === d.check_id) ?? null;
                  return (
                    <div key={i} className="card p-4">
                      <div className="flex flex-wrap items-center gap-2">
                        {typeof d.severity === "string" &&
                          ["high", "medium", "low"].includes(d.severity) && (
                            <SeverityBadge severity={d.severity as Severity} />
                          )}
                        {d.check_id && (
                          <Chip className="border-amber-200 bg-amber-50 text-amber-900">
                            {String(d.check_id)}
                          </Chip>
                        )}
                        {dbRow && dbRow.status !== "open" && (
                          <span className="ml-auto">
                            <FindingStatusBadge status={dbRow.status} />
                          </span>
                        )}
                      </div>
                      <p className="mt-2 text-[13.5px] leading-relaxed text-zinc-700">
                        {String(d.message ?? "")}
                      </p>
                      {dbRow && canReview && (
                        <div className="mt-3 flex gap-2 border-t border-line pt-3">
                          <Button
                            variant="secondary"
                            size="sm"
                            loading={busy === `${dbRow.id}:approved`}
                            onClick={() => review(dbRow, "approved")}
                          >
                            <ThumbsUp className="size-3.5" aria-hidden />
                            Approve
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            loading={busy === `${dbRow.id}:flagged`}
                            onClick={() => review(dbRow, "flagged")}
                          >
                            <Flag className="size-3.5" aria-hidden />
                            Flag
                          </Button>
                          <Button
                            variant="secondary"
                            size="sm"
                            loading={busy === `${dbRow.id}:dismissed`}
                            onClick={() => review(dbRow, "dismissed")}
                          >
                            <Trash2 className="size-3.5" aria-hidden />
                            Dismiss
                          </Button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          )}

          {/* advisories */}
          {advisories.length > 0 && (
            <section aria-label="Advisories">
              <h3 className="mb-3 flex items-center gap-2 text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
                <Info className="size-4 text-violet-600" aria-hidden />
                Advisories · {advisories.length}
              </h3>
              <div className="space-y-2">
                {advisories.map((a: FailedCheck, i) => (
                  <div
                    key={i}
                    className="rounded-xl border border-violet-200/70 bg-violet-50/50 p-3.5 text-[13px] leading-relaxed text-violet-950"
                  >
                    {a.check_id && (
                      <span className="mr-2 font-mono text-[11px] font-bold text-violet-600">
                        {String(a.check_id)}
                      </span>
                    )}
                    {String(a.message ?? "")}
                    <span className="mt-1 block text-[11.5px] text-violet-800/60">
                      Informational — advertiser-level obligation; never gates
                      the verdict.
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* verification */}
          {verification && (
            <section aria-label="Deterministic verification">
              <h3 className="mb-3 flex items-center gap-2 text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
                <ShieldCheck className="size-4 text-violet-600" aria-hidden />
                Deterministic verification
              </h3>
              <div className="card p-4">
                <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div>
                    <dt className="text-[10.5px] font-bold tracking-wider text-zinc-400 uppercase">
                      Soundness
                    </dt>
                    <dd
                      className={cn(
                        "mt-0.5 text-[15px] font-extrabold",
                        verification.review_passed ? "text-emerald-700" : "text-amber-700"
                      )}
                    >
                      {verification.review_passed ? "Passed" : "Not passed"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10.5px] font-bold tracking-wider text-zinc-400 uppercase">
                      Checks run
                    </dt>
                    <dd className="mt-0.5 text-[15px] font-extrabold text-ink-900 tabular-nums">
                      {verification.checks_run ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10.5px] font-bold tracking-wider text-zinc-400 uppercase">
                      Review failures
                    </dt>
                    <dd className="mt-0.5 text-[15px] font-extrabold text-ink-900 tabular-nums">
                      {verification.failed_checks?.length ?? 0}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10.5px] font-bold tracking-wider text-zinc-400 uppercase">
                      Ruleset
                    </dt>
                    <dd className="mt-0.5 truncate font-mono text-[12px] font-bold text-ink-900">
                      {verification.ruleset_version || "—"}
                    </dd>
                  </div>
                </dl>
                {(verification.failed_checks?.length ?? 0) > 0 && (
                  <div className="mt-4">
                    <Collapsible
                      summary={
                        <span className="text-[13px] font-bold text-ink-900">
                          Failed checks on the final round ·{" "}
                          {verification.failed_checks!.length}
                        </span>
                      }
                    >
                      <ul className="space-y-2">
                        {verification.failed_checks!.map((c, i) => (
                          <li
                            key={i}
                            className="rounded-lg bg-cream p-3 text-[12.5px] leading-relaxed text-zinc-700"
                          >
                            {c.check_id && (
                              <span className="mr-2 font-mono text-[11px] font-bold text-zinc-500">
                                {String(c.check_id)}
                              </span>
                            )}
                            {String(c.message ?? "")}
                          </li>
                        ))}
                      </ul>
                    </Collapsible>
                  </div>
                )}
              </div>
            </section>
          )}

          {/* audit rounds */}
          {(report.rounds?.length ?? 0) > 0 && (
            <section aria-label="Audit rounds">
              <h3 className="mb-3 flex items-center gap-2 text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
                <CheckCheck className="size-4 text-violet-600" aria-hidden />
                Audit trail · {report.rounds!.length} round
                {report.rounds!.length === 1 ? "" : "s"}
              </h3>
              <div className="space-y-2">
                {report.rounds!.map((r, i) => (
                  <Collapsible
                    key={i}
                    summary={
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="text-[13px] font-bold text-ink-900">
                          Round {r.round ?? i + 1}
                        </span>
                        {r.was_rule_engine_callback && (
                          <Chip className="border-zinc-200 bg-zinc-50 text-zinc-600">
                            rule-engine callback
                          </Chip>
                        )}
                        {r.had_human_guidance && (
                          <Chip className="border-amber-200 bg-amber-50 text-amber-800">
                            human guidance
                          </Chip>
                        )}
                        <span
                          className={cn(
                            "text-[12px] font-bold",
                            r.rule_engine_passed === true && "text-emerald-700",
                            r.rule_engine_passed === false && "text-amber-700",
                            r.rule_engine_passed == null && "text-zinc-400"
                          )}
                        >
                          {r.rule_engine_passed === true
                            ? "verified sound"
                            : r.rule_engine_passed === false
                              ? `${r.failed_checks?.length ?? 0} check failure${(r.failed_checks?.length ?? 0) === 1 ? "" : "s"}`
                              : "not audited"}
                        </span>
                      </span>
                    }
                  >
                    <div className="space-y-3 text-[12.5px] leading-relaxed text-zinc-600">
                      {r.feedback_sent_to_llm && (
                        <div>
                          <p className="text-[10.5px] font-bold tracking-wider text-zinc-400 uppercase">
                            Feedback sent into this round
                          </p>
                          <pre className="mt-1 max-h-44 overflow-auto rounded-lg bg-cream p-3 font-sans break-words whitespace-pre-wrap">
                            {r.feedback_sent_to_llm}
                          </pre>
                        </div>
                      )}
                      <p>
                        {r.llm_review?.findings?.length ?? 0} finding
                        {(r.llm_review?.findings?.length ?? 0) === 1 ? "" : "s"} produced
                        {(r.failed_checks?.length ?? 0) > 0 &&
                          ` · ${r.failed_checks!.length} failed check${r.failed_checks!.length === 1 ? "" : "s"} on audit`}
                      </p>
                    </div>
                  </Collapsible>
                ))}
              </div>
            </section>
          )}

          {/* warnings */}
          {(report.warnings?.length ?? 0) > 0 && (
            <section aria-label="Warnings" className="rounded-xl border border-amber-200 bg-amber-50/70 p-4">
              <p className="text-[11px] font-bold tracking-wider text-amber-800 uppercase">
                Warnings
              </p>
              <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[12.5px] leading-relaxed text-amber-900">
                {report.warnings!.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </section>
          )}

          {/* provenance */}
          <section aria-label="Provenance" className="card p-4">
            <h3 className="flex items-center gap-2 text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
              <Fingerprint className="size-4 text-violet-600" aria-hidden />
              Provenance
            </h3>
            <dl className="mt-3 grid gap-x-6 gap-y-2.5 font-mono text-[12px] sm:grid-cols-2">
              {[
                ["model", run.model_id ?? report.llm_review?.llm_meta?.model],
                ["prompt", run.prompt_version ?? report.llm_review?.llm_meta?.prompt_version],
                ["ruleset", run.rulepack_version ?? verification?.ruleset_version],
                ["corpus", run.rag_corpus_hash ?? report.llm_review?.llm_meta?.rag_corpus_hash],
                ["engine run", report.run_id ?? run.engine_run_id],
                ["tier", report.tier ?? run.tier],
              ]
                .filter(([, v]) => v)
                .map(([k, v]) => (
                  <div key={k as string} className="flex justify-between gap-3 border-b border-line/70 pb-1.5">
                    <dt className="text-zinc-400">{k}</dt>
                    <dd className="truncate font-semibold text-ink-800">{String(v)}</dd>
                  </div>
                ))}
              <div className="flex justify-between gap-3 border-b border-line/70 pb-1.5">
                <dt className="text-zinc-400">submitted</dt>
                <dd className="font-semibold text-ink-800">
                  {formatDateTime(run.created_at)}
                </dd>
              </div>
              <div className="flex justify-between gap-3 border-b border-line/70 pb-1.5">
                <dt className="text-zinc-400">duration</dt>
                <dd className="font-semibold text-ink-800">
                  {formatDuration(run.started_at, run.finished_at)}
                </dd>
              </div>
              {(run.input_tokens ?? 0) > 0 && (
                <div className="flex justify-between gap-3 border-b border-line/70 pb-1.5">
                  <dt className="text-zinc-400">tokens</dt>
                  <dd className="font-semibold text-ink-800">
                    {formatNumber(run.input_tokens)} in ·{" "}
                    {formatNumber(run.output_tokens)} out
                  </dd>
                </div>
              )}
              {(report.llm_review?.frameworks_evaluated?.length ?? 0) > 0 && (
                <div className="flex justify-between gap-3 border-b border-line/70 pb-1.5 sm:col-span-2">
                  <dt className="text-zinc-400">frameworks</dt>
                  <dd className="truncate font-semibold text-ink-800">
                    {report.llm_review!.frameworks_evaluated!.join(", ")}
                  </dd>
                </div>
              )}
              {(report.llm_review?.reviewed_clear?.length ?? 0) > 0 && (
                <div className="flex justify-between gap-3 sm:col-span-2">
                  <dt className="text-zinc-400">reviewed clear</dt>
                  <dd className="truncate font-semibold text-emerald-700">
                    {report.llm_review!.reviewed_clear!.join(", ")}
                  </dd>
                </div>
              )}
            </dl>
          </section>
        </div>
      </div>
    </div>
  );
}

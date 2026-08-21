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

/** Verdicts meaning a framework did NOT come back clean. Mirrors
 *  engine/report.py::ADVERSE_VERDICTS — the rule engine counts
 *  violation/potential_violation, and the product format's `needs_review`
 *  maps onto potential_violation before the checks run. */
const ADVERSE_VERDICTS = new Set(["violation", "potential_violation", "needs_review"]);

/** Includes `critical`, which SEVERITY_ORDER (a display list) omits. */
const SEVERITY_RANK: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

type FrameworkStatus = "failed" | "passed" | "not_reviewed";

interface FrameworkRow {
  framework: string;
  status: FrameworkStatus;
  findings: number;
  worst: string | null;
}

function worstSeverity(severities: string[]): string | null {
  const ranked = [...severities].sort(
    (a, b) => (SEVERITY_RANK[a] ?? 99) - (SEVERITY_RANK[b] ?? 99)
  );
  return ranked[0] ?? null;
}

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
    <div className="rounded-xl border border-line bg-surface">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <span className="min-w-0 flex-1">{summary}</span>
        <ChevronDown
          className={cn(
            "size-4 shrink-0 text-subtle transition-transform",
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
        <span className="font-mono text-[11px] font-bold text-subtle">
          F{index + 1}
        </span>
        {finding.severity && <SeverityBadge severity={finding.severity} />}
        {finding.verdict && <VerdictBadge verdict={finding.verdict} />}
        <span className="text-[12px] font-bold text-subtle">
          {frameworkLabel(finding.framework)}
        </span>
        {dbRow && dbRow.status !== "open" && (
          <span className="ml-auto">
            <FindingStatusBadge status={dbRow.status} />
          </span>
        )}
      </div>

      {finding.quoted_evidence && (
        <blockquote className="mt-3 flex gap-2.5 rounded-lg border-l-2 border-line-strong bg-tint p-3">
          <Quote className="mt-0.5 size-3.5 shrink-0 text-subtle" aria-hidden />
          <p className="text-[13px] leading-relaxed text-body italic">
            “{finding.quoted_evidence}”
          </p>
        </blockquote>
      )}

      {finding.reasoning && (
        <p className="mt-3 text-[13.5px] leading-relaxed text-muted">
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
        <div className="mt-3 flex items-start gap-2.5 rounded-lg border border-line bg-hover p-3">
          <Wrench className="mt-0.5 size-3.5 shrink-0 text-subtle" aria-hidden />
          <div>
            <p className="text-[11px] font-bold tracking-wider text-subtle uppercase">
              Suggested measures
            </p>
            <p className="mt-0.5 text-[13px] leading-relaxed text-muted">
              {finding.scope_of_improvement}
            </p>
            <p className="mt-1.5 text-[11px] leading-relaxed text-subtle italic">
              A suggestion for your compliance team to evaluate — not legal
              advice, and not a clearance of the ad.
            </p>
          </div>
        </div>
      )}

      {((finding.cited_segment_ids?.length ?? 0) > 0 ||
        (finding.cited_entity_ids?.length ?? 0) > 0) && (
        <p className="mt-2.5 font-mono text-[10.5px] text-subtle">
          cites{" "}
          {[...(finding.cited_segment_ids ?? []), ...(finding.cited_entity_ids ?? [])].join(
            " · "
          )}
        </p>
      )}

      {dbRow && canReview && (
        <div className="mt-3.5 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <span className="mr-1 text-[11px] font-bold tracking-wider text-subtle uppercase">
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
              dbRow.status === "flagged" && "!border-warn-line !bg-warn-soft !text-warn"
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
            className={cn(dbRow.status === "dismissed" && "!text-subtle")}
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

  /** Per-framework pass/fail roll-up. Mirrors engine/report.py::
   *  framework_status(): the work order is the LLM's own
   *  frameworks_evaluated (what ALL-COV-001 graded it against) plus any
   *  framework the org's plan removed before the review ran. */
  const frameworkRows = useMemo<FrameworkRow[]>(() => {
    const evaluated = report.llm_review?.frameworks_evaluated ?? [];
    // Structured source: the worker path stores the whole engine result, so
    // provenance carries the list. Legacy sync-path runs (engine CLI) persist
    // only layer outputs — recover the same list from the warning the engine
    // writes verbatim in saas.py / worker/executor.py, so the panel never
    // contradicts the warning shown below it.
    const dropped =
      (report.provenance?.saas as
        | { frameworks_dropped_by_plan?: string[] }
        | undefined)?.frameworks_dropped_by_plan ??
      (report.warnings ?? [])
        .map(
          (w) =>
            /frameworks outside the .* plan were not reviewed:\s*(.+)$/i.exec(w)?.[1]
        )
        .filter((m): m is string => Boolean(m))
        .flatMap((m) => m.split(",").map((s) => s.trim()))
        .filter(Boolean);

    const hits = new Map<string, string[]>();
    for (const f of llmFindings) {
      if (!ADVERSE_VERDICTS.has(String(f.verdict))) continue;
      const fw = f.framework ?? "?";
      hits.set(fw, [...(hits.get(fw) ?? []), String(f.severity ?? "low")]);
    }

    const rows: FrameworkRow[] = [];
    const seen = new Set<string>();
    const push = (framework: string, status: FrameworkStatus, sev: string[]) => {
      if (seen.has(framework)) return;
      seen.add(framework);
      rows.push({
        framework,
        status,
        findings: sev.length,
        worst: worstSeverity(sev),
      });
    };

    for (const fw of evaluated) {
      const sev = hits.get(fw) ?? [];
      push(fw, sev.length ? "failed" : "passed", sev);
    }
    // A finding may name a framework outside frameworks_evaluated only if
    // ALL-CON-005 did not hold that round — surface it, never silently drop.
    for (const [fw, sev] of hits) push(fw, "failed", sev);
    for (const fw of dropped) push(fw, "not_reviewed", []);

    const statusOrder: Record<FrameworkStatus, number> = {
      failed: 0,
      passed: 1,
      not_reviewed: 2,
    };
    return rows.sort(
      (a, b) =>
        statusOrder[a.status] - statusOrder[b.status] ||
        (SEVERITY_RANK[a.worst ?? ""] ?? 99) - (SEVERITY_RANK[b.worst ?? ""] ?? 99)
    );
  }, [report.llm_review, report.provenance, report.warnings, llmFindings]);

  const frameworkTally = useMemo(
    () => ({
      passed: frameworkRows.filter((r) => r.status === "passed").length,
      failed: frameworkRows.filter((r) => r.status === "failed").length,
      skipped: frameworkRows.filter((r) => r.status === "not_reviewed").length,
    }),
    [frameworkRows]
  );

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
          tone: "border-fail-line bg-fail-soft",
          icon: <CircleAlert className="size-5 text-fail" aria-hidden />,
          title: "The review could not be completed",
          text: report.llm_error ?? "The language-model provider failed.",
        }
      : report.status === "human_review"
        ? {
            tone: "border-warn-line bg-warn-soft",
            icon: <FileWarning className="size-5 text-warn" aria-hidden />,
            title: "Interim report — awaiting human review",
            text: "Findings below reflect the latest round; resume the run above to finish.",
          }
        : potentialViolations + defects.length > 0
          ? {
              tone: "border-line-strong bg-tint",
              icon: <ShieldCheck className="size-5 text-muted" aria-hidden />,
              title: `Review verified — ${potentialViolations + defects.length} item${potentialViolations + defects.length === 1 ? "" : "s"} need attention`,
              text: "The deterministic layer verified this review's soundness. Work the findings below.",
            }
          : {
              tone: "border-pass-line bg-pass-soft",
              icon: <BadgeCheck className="size-5 text-pass" aria-hidden />,
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
        <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl bg-surface shadow-(--shadow-soft)">
          {banner.icon}
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-[16px] font-extrabold text-strong">{banner.title}</h2>
          <p className="mt-0.5 text-[13px] leading-relaxed text-muted">
            {banner.text}
          </p>
        </div>
        <div className="flex items-center gap-4">
          <dl className="hidden items-center gap-4 text-center sm:flex">
            <div>
              <dt className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                Findings
              </dt>
              <dd className="text-lg font-extrabold text-strong tabular-nums">
                {llmFindings.length}
              </dd>
            </div>
            <div>
              <dt className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                Checks
              </dt>
              <dd className="text-lg font-extrabold text-strong tabular-nums">
                {verification?.checks_run ?? "—"}
              </dd>
            </div>
            <div>
              <dt className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                Rounds
              </dt>
              <dd className="text-lg font-extrabold text-strong tabular-nums">
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
          {/* which regulation frameworks applied, and how each came out */}
          {frameworkRows.length > 0 && (
            <section aria-label="Regulation frameworks" className="card p-5">
              <h3 className="flex items-center gap-2 text-[13px] font-extrabold tracking-wide text-strong uppercase">
                <ShieldCheck className="size-4 text-subtle" aria-hidden />
                Regulation frameworks
              </h3>
              <p className="mt-1 text-[12.5px] leading-relaxed text-subtle">
                {frameworkTally.passed} passed · {frameworkTally.failed} failed
                {frameworkTally.skipped > 0
                  ? ` · ${frameworkTally.skipped} not reviewed`
                  : ""}{" "}
                — every framework the router applied to this creative.
              </p>
              <ul className="mt-3 divide-y divide-line">
                {frameworkRows.map((r) => (
                  <li key={r.framework} className="flex items-center gap-3 py-2.5">
                    <span
                      className={cn(
                        "w-[108px] shrink-0 rounded-md border px-2 py-1 text-center text-[11px] font-extrabold tracking-wide uppercase",
                        r.status === "failed" &&
                          "border-fail-line bg-fail-soft text-fail",
                        r.status === "passed" &&
                          "border-pass-line bg-pass-soft text-pass",
                        r.status === "not_reviewed" &&
                          "border-line bg-tint text-subtle"
                      )}
                    >
                      {r.status === "not_reviewed" ? "Not reviewed" : r.status}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[13.5px] font-semibold text-strong">
                      {frameworkLabel(r.framework)}
                    </span>
                    <span className="shrink-0 text-[12px] text-subtle">
                      {r.status === "failed"
                        ? `${r.findings} finding${r.findings === 1 ? "" : "s"}${
                            r.worst ? ` · worst ${r.worst}` : ""
                          }`
                        : r.status === "passed"
                          ? "No issues found"
                          : `Not in the ${report.tier ?? ""} plan`}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {llmFindings.length === 0 ? (
            <section className="card p-6 text-center">
              <BadgeCheck className="mx-auto size-7 text-pass" aria-hidden />
              <p className="mt-2 text-[15px] font-bold text-strong">
                No findings from the grounded review
              </p>
              <p className="mx-auto mt-1 max-w-sm text-[13px] text-subtle">
                The review evaluated the creative against the applicable
                frameworks and raised nothing to work.
              </p>
            </section>
          ) : (
            grouped.map((group) => (
              <section key={group.severity} aria-label={`${group.severity} severity findings`}>
                <div className="mb-3 flex items-center gap-2.5">
                  <SeverityBadge severity={group.severity} />
                  <span className="text-[12px] font-bold text-subtle">
                    {group.items.length} finding{group.items.length === 1 ? "" : "s"}
                  </span>
                  {needsReviewCount > 0 && group === grouped[0] && (
                    <span className="ml-auto text-[11.5px] text-subtle">
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
              <h3 className="mb-3 flex items-center gap-2 text-[13px] font-extrabold tracking-wide text-strong uppercase">
                <FileWarning className="size-4 text-warn" aria-hidden />
                Asset defects · {defects.length}
              </h3>
              <p className="mb-3 -mt-1.5 text-[12.5px] leading-relaxed text-subtle">
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
                          <Chip className="border-warn-line bg-warn-soft text-warn">
                            {String(d.check_id)}
                          </Chip>
                        )}
                        {dbRow && dbRow.status !== "open" && (
                          <span className="ml-auto">
                            <FindingStatusBadge status={dbRow.status} />
                          </span>
                        )}
                      </div>
                      <p className="mt-2 text-[13.5px] leading-relaxed text-muted">
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
              <h3 className="mb-3 flex items-center gap-2 text-[13px] font-extrabold tracking-wide text-strong uppercase">
                <Info className="size-4 text-muted" aria-hidden />
                Advisories · {advisories.length}
              </h3>
              <div className="space-y-2">
                {advisories.map((a: FailedCheck, i) => (
                  <div
                    key={i}
                    className="rounded-xl border border-line bg-tint p-3.5 text-[13px] leading-relaxed text-muted"
                  >
                    {a.check_id && (
                      <span className="mr-2 font-mono text-[11px] font-bold text-muted">
                        {String(a.check_id)}
                      </span>
                    )}
                    {String(a.message ?? "")}
                    <span className="mt-1 block text-[11.5px] text-subtle">
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
              <h3 className="mb-3 flex items-center gap-2 text-[13px] font-extrabold tracking-wide text-strong uppercase">
                <ShieldCheck className="size-4 text-muted" aria-hidden />
                Deterministic verification
              </h3>
              <div className="card p-4">
                <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <div>
                    <dt className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                      Soundness
                    </dt>
                    <dd
                      className={cn(
                        "mt-0.5 text-[15px] font-extrabold",
                        verification.review_passed ? "text-pass" : "text-warn"
                      )}
                    >
                      {verification.review_passed ? "Passed" : "Not passed"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                      Checks run
                    </dt>
                    <dd className="mt-0.5 text-[15px] font-extrabold text-strong tabular-nums">
                      {verification.checks_run ?? "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                      Review failures
                    </dt>
                    <dd className="mt-0.5 text-[15px] font-extrabold text-strong tabular-nums">
                      {verification.failed_checks?.length ?? 0}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                      Ruleset
                    </dt>
                    <dd className="mt-0.5 truncate font-mono text-[12px] font-bold text-strong">
                      {verification.ruleset_version || "—"}
                    </dd>
                  </div>
                </dl>
                {(verification.failed_checks?.length ?? 0) > 0 && (
                  <div className="mt-4">
                    <Collapsible
                      summary={
                        <span className="text-[13px] font-bold text-strong">
                          Failed checks on the final round ·{" "}
                          {verification.failed_checks!.length}
                        </span>
                      }
                    >
                      <ul className="space-y-2">
                        {verification.failed_checks!.map((c, i) => (
                          <li
                            key={i}
                            className="rounded-lg bg-surface p-3 text-[12.5px] leading-relaxed text-muted"
                          >
                            {c.check_id && (
                              <span className="mr-2 font-mono text-[11px] font-bold text-subtle">
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
              <h3 className="mb-3 flex items-center gap-2 text-[13px] font-extrabold tracking-wide text-strong uppercase">
                <CheckCheck className="size-4 text-muted" aria-hidden />
                Audit trail · {report.rounds!.length} round
                {report.rounds!.length === 1 ? "" : "s"}
              </h3>
              <div className="space-y-2">
                {report.rounds!.map((r, i) => (
                  <Collapsible
                    key={i}
                    summary={
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="text-[13px] font-bold text-strong">
                          Round {r.round ?? i + 1}
                        </span>
                        {r.was_rule_engine_callback && (
                          <Chip className="border-line bg-tint text-muted">
                            rule-engine callback
                          </Chip>
                        )}
                        {r.had_human_guidance && (
                          <Chip className="border-warn-line bg-warn-soft text-warn">
                            human guidance
                          </Chip>
                        )}
                        <span
                          className={cn(
                            "text-[12px] font-bold",
                            r.rule_engine_passed === true && "text-pass",
                            r.rule_engine_passed === false && "text-warn",
                            r.rule_engine_passed == null && "text-subtle"
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
                    <div className="space-y-3 text-[12.5px] leading-relaxed text-muted">
                      {r.feedback_sent_to_llm && (
                        <div>
                          <p className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                            Feedback sent into this round
                          </p>
                          <pre className="mt-1 max-h-44 overflow-auto rounded-lg bg-surface p-3 font-sans break-words whitespace-pre-wrap">
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
            <section aria-label="Warnings" className="rounded-xl border border-warn-line bg-warn-soft p-4">
              <p className="text-[11px] font-bold tracking-wider text-warn uppercase">
                Warnings
              </p>
              <ul className="mt-1.5 list-disc space-y-1 pl-4 text-[12.5px] leading-relaxed text-warn">
                {report.warnings!.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </section>
          )}

          {/* provenance */}
          <section aria-label="Provenance" className="card p-4">
            <h3 className="flex items-center gap-2 text-[13px] font-extrabold tracking-wide text-strong uppercase">
              <Fingerprint className="size-4 text-muted" aria-hidden />
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
                    <dt className="text-subtle">{k}</dt>
                    <dd className="truncate font-semibold text-body">{String(v)}</dd>
                  </div>
                ))}
              <div className="flex justify-between gap-3 border-b border-line/70 pb-1.5">
                <dt className="text-subtle">submitted</dt>
                <dd className="font-semibold text-body">
                  {formatDateTime(run.created_at)}
                </dd>
              </div>
              <div className="flex justify-between gap-3 border-b border-line/70 pb-1.5">
                <dt className="text-subtle">duration</dt>
                <dd className="font-semibold text-body">
                  {formatDuration(run.started_at, run.finished_at)}
                </dd>
              </div>
              {(run.input_tokens ?? 0) > 0 && (
                <div className="flex justify-between gap-3 border-b border-line/70 pb-1.5">
                  <dt className="text-subtle">tokens</dt>
                  <dd className="font-semibold text-body">
                    {formatNumber(run.input_tokens)} in ·{" "}
                    {formatNumber(run.output_tokens)} out
                  </dd>
                </div>
              )}
              {(report.llm_review?.frameworks_evaluated?.length ?? 0) > 0 && (
                <div className="flex justify-between gap-3 border-b border-line/70 pb-1.5 sm:col-span-2">
                  <dt className="text-subtle">frameworks</dt>
                  <dd className="truncate font-semibold text-body">
                    {report.llm_review!.frameworks_evaluated!.join(", ")}
                  </dd>
                </div>
              )}
              {(report.llm_review?.reviewed_clear?.length ?? 0) > 0 && (
                <div className="flex justify-between gap-3 sm:col-span-2">
                  <dt className="text-subtle">reviewed clear</dt>
                  <dd className="truncate font-semibold text-pass">
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

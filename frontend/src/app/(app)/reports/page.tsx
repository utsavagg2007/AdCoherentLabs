"use client";

/** Reports: run history with status filters + the findings review queue. */

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ArrowRight, ClipboardList, Filter, Flag, ThumbsUp, Trash2 } from "lucide-react";
import { PageBody, PageHeader } from "@/components/app/page-header";
import { useApi, useOrg } from "@/components/providers";
import { Button } from "@/components/ui/button";
import {
  FindingStatusBadge,
  RunStatusBadge,
  SeverityBadge,
  VerdictBadge,
} from "@/components/ui/badge";
import { EmptyState, ErrorPanel, Skeleton } from "@/components/ui/feedback";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import { isApiError } from "@/lib/api";
import { useAsyncData } from "@/lib/hooks";
import { RUN_STATUS_LABEL, frameworkLabel } from "@/lib/labels";
import type {
  FindingStatus,
  RunRow,
  RunStatus,
  Severity,
} from "@/lib/types";
import { formatDateTime, formatDuration, truncate } from "@/lib/utils";

const RUN_STATUSES: RunStatus[] = [
  "queued",
  "running_cv",
  "running_nlp",
  "running_llm",
  "running_rules",
  "reconciling",
  "complete",
  "human_review",
  "failed",
];

function RunsTab() {
  const api = useApi();
  const { orgId } = useOrg();
  const [status, setStatus] = useState<string>("");
  const [extra, setExtra] = useState<RunRow[]>([]);
  const [nextBefore, setNextBefore] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const first = useAsyncData(
    async (s) => {
      const page = await api.listRuns({ status: status || null, limit: 50 }, s);
      setExtra([]);
      setNextBefore(page.next_before);
      return page;
    },
    [api, orgId, status]
  );

  const rows = [...(first.data?.runs ?? []), ...extra];

  async function loadMore() {
    if (!nextBefore) return;
    setLoadingMore(true);
    try {
      const page = await api.listRuns({
        status: status || null,
        before: nextBefore,
        limit: 50,
      });
      setExtra((p) => [...p, ...page.runs]);
      setNextBefore(page.next_before && page.runs.length ? page.next_before : null);
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center gap-2.5">
        <Filter className="size-4 text-zinc-400" aria-hidden />
        <label htmlFor="run-status" className="sr-only">
          Filter by status
        </label>
        <select
          id="run-status"
          className="input !w-auto !py-2 text-[13px]"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="">All statuses</option>
          {RUN_STATUSES.map((s) => (
            <option key={s} value={s}>
              {RUN_STATUS_LABEL[s]}
            </option>
          ))}
        </select>
      </div>

      {first.error ? (
        <ErrorPanel error={first.error} onRetry={() => first.refresh()} />
      ) : first.loading ? (
        <div className="space-y-3">
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<ClipboardList className="size-5" aria-hidden />}
          title={status ? "No runs with this status" : "No runs yet"}
          description={
            status
              ? "Clear the filter to see the full history."
              : "Runs appear here the moment a submission is accepted."
          }
        />
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[640px] text-left">
            <thead>
              <tr className="border-b border-line text-[11px] font-bold tracking-wider text-zinc-400 uppercase">
                <th className="px-4 py-3">Run</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3">Duration</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3" aria-label="Open" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.map((r) => (
                <tr key={r.id} className="group transition-colors hover:bg-cream/70">
                  <td className="px-4 py-3.5">
                    <Link
                      href={`/runs/${r.id}`}
                      className="font-mono text-[12.5px] font-bold text-ink-900 group-hover:text-violet-800"
                    >
                      {r.id.slice(0, 8)}
                    </Link>
                    <span className="ml-2 text-[11px] text-zinc-400">{r.tier}</span>
                  </td>
                  <td className="px-4 py-3.5 text-[12.5px] whitespace-nowrap text-zinc-500">
                    {formatDateTime(r.created_at)}
                  </td>
                  <td className="px-4 py-3.5 text-[12.5px] text-zinc-500 tabular-nums">
                    {formatDuration(r.started_at, r.finished_at)}
                  </td>
                  <td className="px-4 py-3.5">
                    <RunStatusBadge status={r.status} />
                  </td>
                  <td className="px-4 py-3.5 text-right">
                    <Link
                      href={`/runs/${r.id}`}
                      className="inline-flex items-center gap-1 text-[12.5px] font-bold text-violet-700 hover:text-violet-900"
                    >
                      Open
                      <ArrowRight className="size-3.5" aria-hidden />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {nextBefore && (
            <div className="border-t border-line p-3 text-center">
              <Button variant="secondary" size="sm" onClick={loadMore} loading={loadingMore}>
                Load older runs
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FindingsTab() {
  const api = useApi();
  const { orgId, role } = useOrg();
  const { toast } = useToast();
  const [statusFilter, setStatusFilter] = useState<FindingStatus | "">("open");
  const [severityFilter, setSeverityFilter] = useState<Severity | "">("");
  const [busy, setBusy] = useState<string | null>(null);

  const findings = useAsyncData(
    (s) => api.listFindings({ status: statusFilter || null, limit: 300 }, s),
    [api, orgId, statusFilter]
  );

  const canReview = role !== null && role !== "viewer";
  const rows = (findings.data?.findings ?? []).filter(
    (f) => !severityFilter || f.severity === severityFilter
  );

  async function act(id: string, status: Exclude<FindingStatus, "open">) {
    setBusy(`${id}:${status}`);
    try {
      await api.reviewFinding(id, status);
      findings.refresh({ silent: true });
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

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        <Filter className="size-4 text-zinc-400" aria-hidden />
        <label htmlFor="f-status" className="sr-only">
          Filter by workflow status
        </label>
        <select
          id="f-status"
          className="input !w-auto !py-2 text-[13px]"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as FindingStatus | "")}
        >
          <option value="">Any status</option>
          <option value="open">Open</option>
          <option value="approved">Approved</option>
          <option value="flagged">Flagged</option>
          <option value="dismissed">Dismissed</option>
        </select>
        <label htmlFor="f-severity" className="sr-only">
          Filter by severity
        </label>
        <select
          id="f-severity"
          className="input !w-auto !py-2 text-[13px]"
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value as Severity | "")}
        >
          <option value="">Any severity</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
      </div>

      {findings.error ? (
        <ErrorPanel error={findings.error} onRetry={() => findings.refresh()} />
      ) : findings.loading ? (
        <div className="space-y-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<ClipboardList className="size-5" aria-hidden />}
          title="Queue clear"
          description="No findings match these filters."
        />
      ) : (
        <ul className="space-y-3">
          {rows.map((f) => (
            <li key={f.id} className="card p-4">
              <div className="flex flex-wrap items-center gap-1.5">
                <SeverityBadge severity={f.severity} />
                <VerdictBadge verdict={f.verdict} />
                <span className="text-[12px] font-bold text-zinc-500">
                  {frameworkLabel(f.framework)}
                </span>
                <span className="ml-auto flex items-center gap-2">
                  <FindingStatusBadge status={f.status} />
                  <Link
                    href={`/runs/${f.run_id}`}
                    className="text-[12px] font-bold text-violet-700 hover:text-violet-900"
                  >
                    View run
                  </Link>
                </span>
              </div>
              <p className="mt-2.5 text-[13.5px] leading-relaxed text-zinc-700">
                {truncate(f.message, 280)}
              </p>
              {f.rule_ref && (
                <p className="mt-1.5 font-mono text-[11px] text-zinc-400">
                  {f.rule_ref}
                </p>
              )}
              {canReview && (
                <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={busy === `${f.id}:approved`}
                    onClick={() => act(f.id, "approved")}
                  >
                    <ThumbsUp className="size-3.5" aria-hidden />
                    Approve
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={busy === `${f.id}:flagged`}
                    onClick={() => act(f.id, "flagged")}
                  >
                    <Flag className="size-3.5" aria-hidden />
                    Flag
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={busy === `${f.id}:dismissed`}
                    onClick={() => act(f.id, "dismissed")}
                  >
                    <Trash2 className="size-3.5" aria-hidden />
                    Dismiss
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ReportsContent() {
  const params = useSearchParams();
  const initialTab = params.get("tab") === "findings" ? "findings" : "runs";
  return (
    <>
      <PageHeader
        title="Reports"
        description="Run history and the findings review queue. Full reports export as JSON from each run."
      />
      <PageBody>
        <Tabs defaultValue={initialTab}>
          <TabsList label="Report views">
            <TabsTrigger value="runs">Runs</TabsTrigger>
            <TabsTrigger value="findings">Findings queue</TabsTrigger>
          </TabsList>
          <TabsContent value="runs" className="mt-5">
            <RunsTab />
          </TabsContent>
          <TabsContent value="findings" className="mt-5">
            <FindingsTab />
          </TabsContent>
        </Tabs>
      </PageBody>
    </>
  );
}

export default function ReportsPage() {
  return (
    <Suspense>
      <ReportsContent />
    </Suspense>
  );
}

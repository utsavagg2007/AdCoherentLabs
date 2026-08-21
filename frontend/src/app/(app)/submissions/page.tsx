"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowRight, SquarePlus } from "lucide-react";
import { PageBody, PageHeader } from "@/components/app/page-header";
import { useApi, useOrg } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { RunStatusBadge } from "@/components/ui/badge";
import {
  EmptyState,
  ErrorPanel,
  Skeleton,
} from "@/components/ui/feedback";
import { SubmissionsArt } from "@/components/app/empty-art";
import { useAsyncData } from "@/lib/hooks";
import type { RunRow, SubmissionRow } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

export default function SubmissionsPage() {
  const api = useApi();
  const { orgId } = useOrg();
  const [extra, setExtra] = useState<SubmissionRow[]>([]);
  const [nextBefore, setNextBefore] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const first = useAsyncData(
    async (s) => {
      const page = await api.listSubmissions(null, 50, s);
      setExtra([]);
      setNextBefore(page.next_before);
      return page;
    },
    [api, orgId]
  );
  // one runs sweep joins latest status client-side (no per-row N+1)
  const runs = useAsyncData((s) => api.listRuns({ limit: 200 }, s), [api, orgId]);

  const latestRunBySubmission = useMemo(() => {
    const map = new Map<string, RunRow>();
    for (const r of runs.data?.runs ?? []) {
      const prev = map.get(r.submission_id);
      if (!prev || r.created_at > prev.created_at) map.set(r.submission_id, r);
    }
    return map;
  }, [runs.data]);

  const rows = [...(first.data?.submissions ?? []), ...extra];

  async function loadMore() {
    if (!nextBefore) return;
    setLoadingMore(true);
    try {
      const page = await api.listSubmissions(nextBefore, 50);
      setExtra((p) => [...p, ...page.submissions]);
      setNextBefore(page.next_before && page.submissions.length ? page.next_before : null);
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Submissions"
        description="Every creative your team has sent for review."
        actions={
          <Button href="/submissions/new">
            <SquarePlus className="size-4" aria-hidden />
            New review
          </Button>
        }
      />
      <PageBody>
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
            art={<SubmissionsArt />}
            title="No submissions yet"
            description="Paste ad copy or upload a creative — the review takes it from there."
            action={
              <Button href="/submissions/new">
                Start your first review
                <ArrowRight className="size-4" aria-hidden />
              </Button>
            }
          />
        ) : (
          <div className="card overflow-x-auto">
            <table className="w-full min-w-[640px] text-left">
              <thead>
                <tr className="border-b border-line text-[11px] font-bold tracking-wider text-subtle uppercase">
                  <th className="px-4 py-3">Title</th>
                  <th className="px-4 py-3">Jurisdictions</th>
                  <th className="px-4 py-3">Submitted</th>
                  <th className="px-4 py-3">Latest run</th>
                  <th className="px-4 py-3" aria-label="Open" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((s) => {
                  const latest = latestRunBySubmission.get(s.id) ?? null;
                  return (
                    <tr key={s.id} className="group transition-colors hover:bg-hover">
                      <td className="px-4 py-3.5">
                        <Link
                          href={`/submissions/${s.id}`}
                          className="font-bold text-strong group-hover:text-body"
                        >
                          {s.title || (
                            <span className="font-mono text-[12px] font-semibold text-subtle">
                              {s.id.slice(0, 8)}
                            </span>
                          )}
                        </Link>
                      </td>
                      <td className="px-4 py-3.5 text-[12.5px] text-subtle">
                        {s.target_jurisdictions?.length
                          ? s.target_jurisdictions.join(", ")
                          : "Nationwide"}
                      </td>
                      <td className="px-4 py-3.5 text-[12.5px] whitespace-nowrap text-subtle">
                        {formatDateTime(s.created_at)}
                      </td>
                      <td className="px-4 py-3.5">
                        {latest ? (
                          <RunStatusBadge status={latest.status} />
                        ) : runs.loading ? (
                          <Skeleton className="h-5 w-20" />
                        ) : (
                          <span className="text-[12px] text-subtle">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3.5 text-right">
                        <Link
                          href={
                            latest ? `/runs/${latest.id}` : `/submissions/${s.id}`
                          }
                          className="inline-flex items-center gap-1 text-[12.5px] font-bold text-strong hover:text-brand-text"
                        >
                          Open
                          <ArrowRight className="size-3.5" aria-hidden />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {nextBefore && (
              <div className="border-t border-line p-3 text-center">
                <Button variant="secondary" size="sm" onClick={loadMore} loading={loadingMore}>
                  Load older submissions
                </Button>
              </div>
            )}
          </div>
        )}
      </PageBody>
    </>
  );
}

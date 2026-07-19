"use client";

import Link from "next/link";
import { use } from "react";
import { ArrowRight, FileImage, FileText, ShieldCheck } from "lucide-react";
import { PageBody, PageHeader } from "@/components/app/page-header";
import { useApi, useOrg } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { Chip, RunStatusBadge } from "@/components/ui/badge";
import { ErrorPanel, PageLoading } from "@/components/ui/feedback";
import { useAsyncData } from "@/lib/hooks";
import { formatDateTime, formatDuration } from "@/lib/utils";

export default function SubmissionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const api = useApi();
  const { orgId } = useOrg();
  const detail = useAsyncData(
    (s) => api.getSubmission(id, s),
    [api, orgId, id]
  );

  if (detail.loading) {
    return (
      <>
        <PageHeader title="Submission" />
        <PageBody>
          <PageLoading label="Loading submission" />
        </PageBody>
      </>
    );
  }
  if (detail.error || !detail.data) {
    return (
      <>
        <PageHeader title="Submission" />
        <PageBody>
          <ErrorPanel error={detail.error} onRetry={() => detail.refresh()} />
        </PageBody>
      </>
    );
  }

  const { submission, assets, runs } = detail.data;
  const kind =
    (submission.params?.pricing_kind as string | undefined) ??
    (assets[0]?.kind as string | undefined) ??
    "—";
  const cards = submission.params?.cards as number | undefined;

  return (
    <>
      <PageHeader
        title={submission.title || `Submission ${submission.id.slice(0, 8)}`}
        description={`Submitted ${formatDateTime(submission.created_at)}`}
        actions={
          runs.length > 0 ? (
            <Button href={`/runs/${runs[runs.length - 1].id}`}>
              Latest run
              <ArrowRight className="size-4" aria-hidden />
            </Button>
          ) : undefined
        }
      />
      <PageBody>
        <div className="space-y-6">
          {/* meta */}
          <section className="card p-4" aria-label="Submission details">
            <dl className="grid gap-x-6 gap-y-3 text-[13px] sm:grid-cols-4">
              <div>
                <dt className="text-[10.5px] font-bold tracking-wider text-zinc-400 uppercase">
                  Format
                </dt>
                <dd className="mt-0.5 font-bold text-ink-900 capitalize">
                  {kind}
                  {kind === "carousel" && cards ? ` · ${cards} cards` : ""}
                </dd>
              </div>
              <div>
                <dt className="text-[10.5px] font-bold tracking-wider text-zinc-400 uppercase">
                  Jurisdictions
                </dt>
                <dd className="mt-0.5 font-bold text-ink-900">
                  {submission.target_jurisdictions?.length
                    ? submission.target_jurisdictions.join(", ")
                    : "Nationwide"}
                </dd>
              </div>
              <div>
                <dt className="text-[10.5px] font-bold tracking-wider text-zinc-400 uppercase">
                  Assets
                </dt>
                <dd className="mt-0.5 font-bold text-ink-900 tabular-nums">
                  {assets.length || "Inline"}
                </dd>
              </div>
              <div>
                <dt className="text-[10.5px] font-bold tracking-wider text-zinc-400 uppercase">
                  Runs
                </dt>
                <dd className="mt-0.5 font-bold text-ink-900 tabular-nums">
                  {runs.length}
                </dd>
              </div>
            </dl>
          </section>

          {/* assets */}
          {assets.length > 0 && (
            <section aria-label="Stored assets">
              <h2 className="mb-3 text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
                Stored assets
              </h2>
              <ul className="grid gap-2 sm:grid-cols-2">
                {assets.map((a, i) => (
                  <li
                    key={a.id}
                    className="flex items-center gap-3 rounded-xl border border-line bg-white p-3"
                  >
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-cream text-zinc-400">
                      {a.kind === "image" ? (
                        <FileImage className="size-4.5" aria-hidden />
                      ) : (
                        <FileText className="size-4.5" aria-hidden />
                      )}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] font-bold text-ink-900 capitalize">
                        {a.kind}
                        {assets.length > 1 ? ` · card ${i + 1}` : ""}
                      </span>
                      <span className="block truncate font-mono text-[11px] text-zinc-400">
                        sha256 {a.checksum.slice(0, 16)}…
                      </span>
                    </span>
                    <Chip className="border-emerald-200 bg-emerald-50 text-emerald-700">
                      <ShieldCheck className="size-3" aria-hidden />
                      {a.scan_status}
                    </Chip>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* runs */}
          <section aria-label="Runs">
            <h2 className="mb-3 text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
              Review runs
            </h2>
            <div className="card divide-y divide-line">
              {runs.length === 0 && (
                <p className="p-4 text-[13px] text-zinc-500">
                  No runs recorded for this submission.
                </p>
              )}
              {[...runs].reverse().map((r) => (
                <Link
                  key={r.id}
                  href={`/runs/${r.id}`}
                  className="flex items-center gap-4 px-4 py-3.5 transition-colors hover:bg-cream/70"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block font-mono text-[12px] font-bold text-ink-800">
                      {r.id.slice(0, 8)}
                      {r.resumed_from_run_id && (
                        <span className="ml-2 rounded-md bg-violet-50 px-1.5 py-0.5 text-[10px] font-bold text-violet-700">
                          resumed
                        </span>
                      )}
                    </span>
                    <span className="mt-0.5 block text-[11.5px] text-zinc-400">
                      {formatDateTime(r.created_at)} ·{" "}
                      {formatDuration(r.started_at, r.finished_at)}
                    </span>
                  </span>
                  <RunStatusBadge status={r.status} />
                  <ArrowRight className="size-4 text-zinc-300" aria-hidden />
                </Link>
              ))}
            </div>
          </section>
        </div>
      </PageBody>
    </>
  );
}

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
                <dt className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                  Format
                </dt>
                <dd className="mt-0.5 font-bold text-strong capitalize">
                  {kind}
                  {kind === "carousel" && cards ? ` · ${cards} cards` : ""}
                </dd>
              </div>
              <div>
                <dt className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                  Jurisdictions
                </dt>
                <dd className="mt-0.5 font-bold text-strong">
                  {submission.target_jurisdictions?.length
                    ? submission.target_jurisdictions.join(", ")
                    : "Nationwide"}
                </dd>
              </div>
              <div>
                <dt className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                  Assets
                </dt>
                <dd className="mt-0.5 font-bold text-strong tabular-nums">
                  {assets.length || "Inline"}
                </dd>
              </div>
              <div>
                <dt className="text-[10.5px] font-bold tracking-wider text-subtle uppercase">
                  Runs
                </dt>
                <dd className="mt-0.5 font-bold text-strong tabular-nums">
                  {runs.length}
                </dd>
              </div>
            </dl>
          </section>

          {/* assets */}
          {assets.length > 0 && (
            <section aria-label="Stored assets">
              <h2 className="mb-3 text-[13px] font-extrabold tracking-wide text-strong uppercase">
                Stored assets
              </h2>
              <ul className="grid gap-2 sm:grid-cols-2">
                {assets.map((a, i) => (
                  <li
                    key={a.id}
                    className="flex items-center gap-3 rounded-xl border border-line bg-surface p-3"
                  >
                    <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-surface text-subtle">
                      {a.kind === "image" ? (
                        <FileImage className="size-4.5" aria-hidden />
                      ) : (
                        <FileText className="size-4.5" aria-hidden />
                      )}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13px] font-bold text-strong capitalize">
                        {a.kind}
                        {assets.length > 1 ? ` · card ${i + 1}` : ""}
                      </span>
                      <span className="block truncate font-mono text-[11px] text-subtle">
                        sha256 {a.checksum.slice(0, 16)}…
                      </span>
                    </span>
                    <Chip className="border-pass-line bg-pass-soft text-pass">
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
            <h2 className="mb-3 text-[13px] font-extrabold tracking-wide text-strong uppercase">
              Review runs
            </h2>
            <div className="card divide-y divide-line">
              {runs.length === 0 && (
                <p className="p-4 text-[13px] text-subtle">
                  No runs recorded for this submission.
                </p>
              )}
              {[...runs].reverse().map((r) => (
                <Link
                  key={r.id}
                  href={`/runs/${r.id}`}
                  className="flex items-center gap-4 px-4 py-3.5 transition-colors hover:bg-hover"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block font-mono text-[12px] font-bold text-body">
                      {r.id.slice(0, 8)}
                      {r.resumed_from_run_id && (
                        <span className="ml-2 rounded-md bg-tint px-1.5 py-0.5 text-[10px] font-bold text-strong">
                          resumed
                        </span>
                      )}
                    </span>
                    <span className="mt-0.5 block text-[11.5px] text-subtle">
                      {formatDateTime(r.created_at)} ·{" "}
                      {formatDuration(r.started_at, r.finished_at)}
                    </span>
                  </span>
                  <RunStatusBadge status={r.status} />
                  <ArrowRight className="size-4 text-muted" aria-hidden />
                </Link>
              ))}
            </div>
          </section>
        </div>
      </PageBody>
    </>
  );
}

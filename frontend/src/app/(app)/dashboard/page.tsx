"use client";

import Link from "next/link";
import {
  ArrowRight,
  CircleDollarSign,
  FileSearch2,
  Gauge,
  Scale,
  ScanSearch,
  ShieldCheck,
  SquarePlus,
} from "lucide-react";
import { PageBody, PageHeader } from "@/components/app/page-header";
import { useApi, useOrg } from "@/components/providers";
import { Button } from "@/components/ui/button";
import {
  RunStatusBadge,
  SeverityBadge,
  SeverityDot,
} from "@/components/ui/badge";
import {
  Disclaimer,
  EmptyState,
  ErrorPanel,
  Skeleton,
} from "@/components/ui/feedback";
import { useAsyncData } from "@/lib/hooks";
import { frameworkLabel } from "@/lib/labels";
import { ACTIVE_RUN_STATUSES, type Severity } from "@/lib/types";
import { formatNumber, timeAgo, truncate } from "@/lib/utils";

const REVIEW_STEPS = [
  {
    icon: ScanSearch,
    title: "Extract",
    text: "OCR and vision turn the creative into structured evidence.",
  },
  {
    icon: FileSearch2,
    title: "Identify",
    text: "NLP finds every claim, qualifier, and disclosure.",
  },
  {
    icon: Scale,
    title: "Ground",
    text: "The AI review cites the regulation text it relied on.",
  },
  {
    icon: ShieldCheck,
    title: "Verify",
    text: "Deterministic checks audit the review before you see it.",
  },
];

export default function DashboardPage() {
  const api = useApi();
  const { orgId, orgName } = useOrg();

  const orgMe = useAsyncData((s) => api.orgMe(s), [api, orgId]);
  const runs = useAsyncData((s) => api.listRuns({ limit: 25 }, s), [api, orgId]);
  const findings = useAsyncData(
    (s) => api.listFindings({ status: "open", limit: 200 }, s),
    [api, orgId]
  );
  const submissions = useAsyncData(
    (s) => api.listSubmissions(null, 8, s),
    [api, orgId]
  );

  const credits = orgMe.data?.credits ?? null;
  const activeRuns =
    runs.data?.runs.filter((r) =>
      (ACTIVE_RUN_STATUSES as string[]).includes(r.status)
    ) ?? [];
  const humanReview =
    runs.data?.runs.filter((r) => r.status === "human_review") ?? [];

  const bySeverity: Record<Severity, number> = { high: 0, medium: 0, low: 0 };
  for (const f of findings.data?.findings ?? []) {
    if (f.severity in bySeverity) bySeverity[f.severity] += 1;
  }
  const openTotal = bySeverity.high + bySeverity.medium + bySeverity.low;

  const isBrandNew =
    !runs.loading &&
    !submissions.loading &&
    (runs.data?.runs.length ?? 0) === 0 &&
    (submissions.data?.submissions.length ?? 0) === 0;

  const firstError = orgMe.error || runs.error;

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={orgName ? `Compliance review activity for ${orgName}.` : undefined}
        actions={
          <Button href="/submissions/new">
            <SquarePlus className="size-4" aria-hidden />
            New review
          </Button>
        }
      />
      <PageBody>
        {firstError ? (
          <ErrorPanel
            error={firstError}
            onRetry={() => {
              orgMe.refresh();
              runs.refresh();
              findings.refresh();
              submissions.refresh();
            }}
          />
        ) : (
          <div className="space-y-6">
            {/* stat row */}
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {/* credits */}
              <div className="card p-4">
                <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-wider text-ink-500 uppercase">
                  <CircleDollarSign className="size-3.5" aria-hidden />
                  Credit balance
                </p>
                {orgMe.loading ? (
                  <Skeleton className="mt-2 h-8 w-24" />
                ) : (
                  <>
                    <p className="mt-1.5 text-3xl font-extrabold text-ink-900 tabular-nums">
                      {formatNumber(credits?.total)}
                    </p>
                    <p className="mt-1 text-[12px] text-ink-500 tabular-nums">
                      {formatNumber(credits?.subscription_credits)} subscription
                      · {formatNumber(credits?.purchased_credits)} purchased
                    </p>
                  </>
                )}
                <Link
                  href="/billing"
                  className="mt-3 inline-flex items-center gap-1 text-[12.5px] font-bold text-ink-900 hover:text-white"
                >
                  Manage credits
                  <ArrowRight className="size-3.5" aria-hidden />
                </Link>
              </div>

              {/* plan */}
              <div className="card p-4">
                <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-wider text-ink-500 uppercase">
                  <Gauge className="size-3.5" aria-hidden />
                  Plan
                </p>
                {orgMe.loading ? (
                  <Skeleton className="mt-2 h-8 w-24" />
                ) : (
                  <>
                    <p className="mt-1.5 text-3xl font-extrabold text-ink-900 capitalize">
                      {orgMe.data?.tier}
                    </p>
                    <p className="mt-1 text-[12px] text-ink-500">
                      {orgMe.data?.entitlements.credits_per_month != null
                        ? `${formatNumber(orgMe.data.entitlements.credits_per_month)} credits / month`
                        : "Custom credit provisioning"}
                      {" · "}
                      {orgMe.data?.entitlements.max_upload_mb ?? 10} MB uploads
                    </p>
                  </>
                )}
                <Link
                  href="/billing"
                  className="mt-3 inline-flex items-center gap-1 text-[12.5px] font-bold text-ink-900 hover:text-white"
                >
                  View plan
                  <ArrowRight className="size-3.5" aria-hidden />
                </Link>
              </div>

              {/* active runs */}
              <div className="card p-4">
                <p className="text-[11px] font-bold tracking-wider text-ink-500 uppercase">
                  Active runs
                </p>
                {runs.loading ? (
                  <Skeleton className="mt-2 h-8 w-16" />
                ) : (
                  <>
                    <p className="mt-1.5 text-3xl font-extrabold text-ink-900 tabular-nums">
                      {activeRuns.length}
                    </p>
                    <p className="mt-1 text-[12px] text-ink-500">
                      {humanReview.length > 0 ? (
                        <span className="font-bold text-amber-300">
                          {humanReview.length} awaiting human review
                        </span>
                      ) : (
                        "in the four-layer pipeline"
                      )}
                    </p>
                  </>
                )}
                <Link
                  href="/reports"
                  className="mt-3 inline-flex items-center gap-1 text-[12.5px] font-bold text-ink-900 hover:text-white"
                >
                  Run history
                  <ArrowRight className="size-3.5" aria-hidden />
                </Link>
              </div>

              {/* open findings */}
              <div className="card p-4">
                <p className="text-[11px] font-bold tracking-wider text-ink-500 uppercase">
                  Open findings
                </p>
                {findings.loading ? (
                  <Skeleton className="mt-2 h-8 w-16" />
                ) : (
                  <>
                    <p className="mt-1.5 text-3xl font-extrabold text-ink-900 tabular-nums">
                      {openTotal}
                    </p>
                    <div className="mt-1.5 flex items-center gap-3 text-[12px] font-semibold text-ink-500 tabular-nums">
                      <span className="inline-flex items-center gap-1">
                        <SeverityDot severity="high" /> {bySeverity.high}
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <SeverityDot severity="medium" /> {bySeverity.medium}
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <SeverityDot severity="low" /> {bySeverity.low}
                      </span>
                    </div>
                  </>
                )}
                <Link
                  href="/reports?tab=findings"
                  className="mt-3 inline-flex items-center gap-1 text-[12.5px] font-bold text-ink-900 hover:text-white"
                >
                  Review queue
                  <ArrowRight className="size-3.5" aria-hidden />
                </Link>
              </div>
            </div>

            {isBrandNew ? (
              <div className="card bg-grid-faint p-8 sm:p-10">
                <div className="mx-auto max-w-2xl text-center">
                  <h2 className="text-xl font-extrabold tracking-tight text-ink-900">
                    Run your first compliance review
                  </h2>
                  <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-ink-500">
                    Paste ad copy or upload a creative. Four layers do the rest
                    — and every finding arrives with its evidence.
                  </p>
                </div>
                <div className="mx-auto mt-8 grid max-w-3xl gap-4 sm:grid-cols-4">
                  {REVIEW_STEPS.map((s, i) => {
                    const Icon = s.icon;
                    return (
                      <div key={s.title} className="text-center">
                        <div className="mx-auto flex size-11 items-center justify-center rounded-2xl border border-white/15 bg-white/6 text-ink-600">
                          <Icon className="size-5" aria-hidden />
                        </div>
                        <p className="mt-2.5 text-[13px] font-bold text-ink-900">
                          {i + 1}. {s.title}
                        </p>
                        <p className="mt-1 text-[12px] leading-relaxed text-ink-500">
                          {s.text}
                        </p>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-8 flex justify-center">
                  <Button href="/submissions/new" size="lg">
                    Start a review
                    <ArrowRight className="size-4" aria-hidden />
                  </Button>
                </div>
              </div>
            ) : (
              <div className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
                {/* recent runs */}
                <section aria-label="Recent runs" className="card overflow-hidden">
                  <div className="flex items-center justify-between border-b border-line px-4 py-3">
                    <h2 className="text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
                      Recent runs
                    </h2>
                    <Link
                      href="/reports"
                      className="text-[12.5px] font-bold text-ink-900 hover:text-white"
                    >
                      View all
                    </Link>
                  </div>
                  {runs.loading ? (
                    <div className="space-y-3 p-4">
                      <Skeleton className="h-10" />
                      <Skeleton className="h-10" />
                      <Skeleton className="h-10" />
                    </div>
                  ) : (runs.data?.runs.length ?? 0) === 0 ? (
                    <div className="p-4">
                      <EmptyState
                        title="No runs yet"
                        description="Submit a creative to start your first review."
                      />
                    </div>
                  ) : (
                    <ul className="divide-y divide-line">
                      {runs.data!.runs.slice(0, 6).map((r) => (
                        <li key={r.id}>
                          <Link
                            href={`/runs/${r.id}`}
                            className="flex items-center gap-4 px-4 py-3 transition-colors hover:bg-cream/70"
                          >
                            <span className="min-w-0 flex-1">
                              <span className="block truncate font-mono text-[12px] font-semibold text-ink-800">
                                {r.id.slice(0, 8)}
                              </span>
                              <span className="mt-0.5 block text-[11.5px] text-ink-500">
                                {timeAgo(r.created_at)} · {r.tier}
                              </span>
                            </span>
                            <RunStatusBadge status={r.status} />
                            <ArrowRight className="size-4 text-ink-700" aria-hidden />
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                {/* recent findings */}
                <section aria-label="Recent findings" className="card overflow-hidden">
                  <div className="flex items-center justify-between border-b border-line px-4 py-3">
                    <h2 className="text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
                      Recent open findings
                    </h2>
                    <Link
                      href="/reports?tab=findings"
                      className="text-[12.5px] font-bold text-ink-900 hover:text-white"
                    >
                      Queue
                    </Link>
                  </div>
                  {findings.loading ? (
                    <div className="space-y-3 p-4">
                      <Skeleton className="h-12" />
                      <Skeleton className="h-12" />
                    </div>
                  ) : (findings.data?.findings.length ?? 0) === 0 ? (
                    <div className="p-4">
                      <EmptyState
                        title="No open findings"
                        description="Findings from completed reviews appear here for triage."
                      />
                    </div>
                  ) : (
                    <ul className="divide-y divide-line">
                      {findings.data!.findings.slice(0, 6).map((f) => (
                        <li key={f.id}>
                          <Link
                            href={`/runs/${f.run_id}`}
                            className="block px-4 py-3 transition-colors hover:bg-cream/70"
                          >
                            <div className="flex items-center gap-2">
                              <SeverityBadge severity={f.severity} />
                              <span className="truncate text-[11.5px] font-semibold text-ink-500">
                                {frameworkLabel(f.framework)}
                              </span>
                            </div>
                            <p className="mt-1.5 line-clamp-2 text-[13px] leading-snug text-ink-800">
                              {truncate(f.message, 140)}
                            </p>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>
            )}

            <Disclaimer />
          </div>
        )}
      </PageBody>
    </>
  );
}

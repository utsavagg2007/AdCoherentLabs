import Link from "next/link";
import { ArrowUpRight, FileWarning, Layers, Inbox, Percent } from "lucide-react";
import { requireContext, getDashboardData } from "@/lib/data";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { RunStatusBadge, SeverityBadge, VerdictBadge } from "@/components/badges";
import { QuotaMeter } from "@/components/quota-meter";
import { buttonClasses } from "@/components/ui/button";
import { timeAgo } from "@/lib/utils";

export const metadata = { title: "Dashboard" };

export default async function DashboardPage() {
  const ctx = await requireContext();
  const data = await getDashboardData(ctx.org.id);
  const openTotal =
    data.openBySeverity.high + data.openBySeverity.medium + data.openBySeverity.low;

  return (
    <>
      <PageHeader
        title={`Good to see you`}
        description={`${ctx.org.name} · ${ctx.quota.tier} plan · ${ctx.quota.model}`}
      >
        <Link href="/submissions/new" className={buttonClasses("primary", "sm")}>
          New submission <ArrowUpRight size={14} />
        </Link>
      </PageHeader>

      {/* Stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-ink-dim">Submissions</CardTitle>
            <Inbox size={15} className="text-ink-faint" />
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold tracking-tight">
              {data.submissionsCount}
            </p>
            <p className="mt-1 text-[11px] text-ink-faint">
              campaigns & asset bundles reviewed
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-ink-dim">Runs in flight</CardTitle>
            <Layers size={15} className="text-ink-faint" />
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold tracking-tight">
              {data.activeRuns}
            </p>
            <p className="mt-1 text-[11px] text-ink-faint">
              queued or moving through the four layers
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-ink-dim">Open findings</CardTitle>
            <FileWarning size={15} className="text-ink-faint" />
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold tracking-tight">{openTotal}</p>
            <div className="mt-2 flex gap-3 text-[11px]">
              <span className="text-rose-300">{data.openBySeverity.high} high</span>
              <span className="text-amber-300">{data.openBySeverity.medium} med</span>
              <span className="text-sky-300">{data.openBySeverity.low} low</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle className="text-ink-dim">Compliance rate</CardTitle>
            <Percent size={15} className="text-ink-faint" />
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold tracking-tight">
              {data.complianceRate == null ? "—" : `${data.complianceRate}%`}
            </p>
            <p className="mt-1 text-[11px] text-ink-faint">
              of recent findings judged compliant or approved
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        {/* Recent runs */}
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Recent analysis runs</CardTitle>
            <Link
              href="/reports"
              className="text-[11px] text-ink-faint hover:text-ink"
            >
              View all →
            </Link>
          </CardHeader>
          <CardContent className="px-0 pb-2">
            <Table>
              <THead>
                <TR className="hover:bg-transparent">
                  <TH>Submission</TH>
                  <TH>Status</TH>
                  <TH>Findings</TH>
                  <TH className="text-right">When</TH>
                </TR>
              </THead>
              <TBody>
                {data.recentRuns.length === 0 && (
                  <TR>
                    <TD colSpan={4} className="py-10 text-center text-ink-faint">
                      No runs yet — upload your first creative.
                    </TD>
                  </TR>
                )}
                {data.recentRuns.map((run) => (
                  <TR key={run.id}>
                    <TD>
                      <Link
                        href={`/runs/${run.id}`}
                        className="font-medium text-ink hover:text-brand"
                      >
                        {run.submissionTitle}
                      </Link>
                      <p className="mt-0.5 font-mono text-[10px] text-ink-faint">
                        {run.model_id ?? "model pending"}
                      </p>
                    </TD>
                    <TD>
                      <RunStatusBadge status={run.status} />
                    </TD>
                    <TD className="font-mono text-xs">{run.findingsCount}</TD>
                    <TD className="text-right text-xs text-ink-faint">
                      {timeAgo(run.created_at)}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>

        {/* Right column: quota + open findings */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Quota</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <QuotaMeter quota={ctx.quota} />
              <Link
                href="/billing"
                className="block text-[11px] text-ink-faint hover:text-ink"
              >
                Manage plan →
              </Link>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Needs your review</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {data.recentFindings.length === 0 && (
                <p className="py-4 text-center text-xs text-ink-faint">
                  No open findings. Clean queue.
                </p>
              )}
              {data.recentFindings.map((f) => (
                <Link
                  key={f.id}
                  href={`/runs/${f.run_id}`}
                  className="block rounded-xl border border-line bg-raised/50 p-3 transition-colors hover:border-line-bright"
                >
                  <div className="flex items-center gap-2">
                    <SeverityBadge severity={f.severity} />
                    <VerdictBadge verdict={f.verdict} />
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs leading-relaxed text-ink-dim">
                    <span className="font-medium text-ink">{f.framework}</span>
                    {f.rule_ref ? ` · ${f.rule_ref}` : ""} — {f.message}
                  </p>
                </Link>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

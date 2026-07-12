import Link from "next/link";
import { Download } from "lucide-react";
import { requireContext, getRuns } from "@/lib/data";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { RunStatusBadge } from "@/components/badges";
import {
  formatCents,
  formatDateTime,
  formatTokens,
  runDuration,
} from "@/lib/utils";

export const metadata = { title: "History & Reports" };

export default async function ReportsPage() {
  const ctx = await requireContext();
  const runs = await getRuns(ctx.org.id);

  return (
    <>
      <PageHeader
        title="History & Reports"
        description="Every run with full provenance — model, prompt, rule pack, cost. Exportable for your compliance file."
      />

      <Card>
        <CardContent className="px-0 py-2">
          <Table>
            <THead>
              <TR className="hover:bg-transparent">
                <TH>Submission</TH>
                <TH>Status</TH>
                <TH>Findings</TH>
                <TH>Model</TH>
                <TH>Rule pack</TH>
                <TH>Tokens</TH>
                <TH>Cost</TH>
                <TH>Duration</TH>
                <TH className="text-right">Started</TH>
                <TH />
              </TR>
            </THead>
            <TBody>
              {runs.length === 0 && (
                <TR>
                  <TD colSpan={10} className="py-14 text-center text-ink-faint">
                    No runs yet.
                  </TD>
                </TR>
              )}
              {runs.map((run) => (
                <TR key={run.id}>
                  <TD>
                    <Link
                      href={`/runs/${run.id}`}
                      className="font-medium text-ink hover:text-brand"
                    >
                      {run.submissionTitle}
                    </Link>
                  </TD>
                  <TD>
                    <RunStatusBadge status={run.status} />
                  </TD>
                  <TD className="font-mono text-xs">{run.findingsCount}</TD>
                  <TD className="font-mono text-[11px] text-ink-dim">
                    {run.model_id ?? "—"}
                  </TD>
                  <TD className="font-mono text-[11px] text-ink-dim">
                    {run.rulepack_version ?? "—"}
                  </TD>
                  <TD className="font-mono text-[11px] text-ink-dim">
                    {run.input_tokens == null
                      ? "—"
                      : `${formatTokens(run.input_tokens)} / ${formatTokens(run.output_tokens)}`}
                  </TD>
                  <TD className="font-mono text-[11px] text-ink-dim">
                    {formatCents(run.cost_cents)}
                  </TD>
                  <TD className="font-mono text-[11px] text-ink-dim">
                    {runDuration(run.started_at, run.finished_at)}
                  </TD>
                  <TD className="text-right text-xs text-ink-faint">
                    {formatDateTime(run.created_at)}
                  </TD>
                  <TD>
                    <a
                      href={`/api/runs/${run.id}/export?format=json`}
                      title="Export findings (JSON)"
                      className="text-ink-faint hover:text-ink"
                    >
                      <Download size={14} />
                    </a>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </CardContent>
      </Card>
    </>
  );
}

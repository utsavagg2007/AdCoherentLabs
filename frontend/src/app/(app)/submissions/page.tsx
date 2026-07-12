import Link from "next/link";
import { Plus } from "lucide-react";
import { requireContext, getSubmissions } from "@/lib/data";
import { PageHeader } from "@/components/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { RunStatusBadge } from "@/components/badges";
import { Badge } from "@/components/ui/badge";
import { buttonClasses } from "@/components/ui/button";
import { formatDateTime } from "@/lib/utils";

export const metadata = { title: "Submissions" };

export default async function SubmissionsPage() {
  const ctx = await requireContext();
  const submissions = await getSubmissions(ctx.org.id);

  return (
    <>
      <PageHeader
        title="Submissions"
        description="Every campaign or asset bundle sent for compliance review."
      >
        <Link href="/submissions/new" className={buttonClasses("primary", "sm")}>
          <Plus size={14} /> New submission
        </Link>
      </PageHeader>

      <Card>
        <CardContent className="px-0 py-2">
          <Table>
            <THead>
              <TR className="hover:bg-transparent">
                <TH>Title</TH>
                <TH>Assets</TH>
                <TH>Latest run</TH>
                <TH className="text-right">Created</TH>
              </TR>
            </THead>
            <TBody>
              {submissions.length === 0 && (
                <TR>
                  <TD colSpan={4} className="py-14 text-center text-ink-faint">
                    Nothing here yet — start with your first creative.
                  </TD>
                </TR>
              )}
              {submissions.map((s) => (
                <TR key={s.id}>
                  <TD>
                    {s.latestRun ? (
                      <Link
                        href={`/runs/${s.latestRun.id}`}
                        className="font-medium text-ink hover:text-brand"
                      >
                        {s.title ?? "Untitled"}
                      </Link>
                    ) : (
                      <span className="font-medium">{s.title ?? "Untitled"}</span>
                    )}
                  </TD>
                  <TD>
                    <div className="flex flex-wrap gap-1">
                      {s.assetKinds.length === 0 && (
                        <span className="text-xs text-ink-faint">—</span>
                      )}
                      {s.assetKinds.map((k, i) => (
                        <Badge key={`${k}-${i}`} className="uppercase">
                          {k}
                        </Badge>
                      ))}
                    </div>
                  </TD>
                  <TD>
                    {s.latestRun ? (
                      <RunStatusBadge status={s.latestRun.status} />
                    ) : (
                      <span className="text-xs text-ink-faint">no run</span>
                    )}
                  </TD>
                  <TD className="text-right text-xs text-ink-faint">
                    {formatDateTime(s.created_at)}
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

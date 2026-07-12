import { NextResponse } from "next/server";
import { getRunDetail, getSessionState } from "@/lib/data";

/**
 * Exports a run's compliance report (findings + provenance) as JSON or CSV.
 * Reads run under the caller's RLS-bound session — tenant isolation holds.
 */
export async function GET(
  request: Request,
  ctx: RouteContext<"/api/runs/[id]/export">,
) {
  const { id } = await ctx.params;
  const state = await getSessionState();
  if (state.kind !== "ready") {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const detail = await getRunDetail(id);
  if (!detail || detail.run.org_id !== state.ctx.org.id) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }

  const url = new URL(request.url);
  const format = url.searchParams.get("format") ?? "json";
  const { run, submission, findings } = detail;

  if (format === "csv") {
    const header = [
      "finding_id",
      "framework",
      "rule_ref",
      "severity",
      "verdict",
      "confidence",
      "status",
      "message",
      "remediation",
    ];
    const rows = findings.map((f) =>
      [
        f.id,
        f.framework,
        f.rule_ref ?? "",
        f.severity,
        f.verdict,
        f.confidence ?? "",
        f.status,
        f.message,
        f.remediation ?? "",
      ]
        .map(csvEscape)
        .join(","),
    );
    return new NextResponse([header.join(","), ...rows].join("\r\n"), {
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": `attachment; filename="adcoherent-run-${run.id.slice(0, 8)}.csv"`,
      },
    });
  }

  const report = {
    generated_at: new Date().toISOString(),
    disclaimer:
      "AdCoherent assists compliance review; this report is decision support, not legal advice.",
    submission: { id: submission.id, title: submission.title },
    run: {
      id: run.id,
      status: run.status,
      provenance: {
        model_id: run.model_id,
        prompt_version: run.prompt_version,
        rulepack_version: run.rulepack_version,
        rag_corpus_hash: run.rag_corpus_hash,
        input_tokens: run.input_tokens,
        output_tokens: run.output_tokens,
        cost_cents: run.cost_cents,
        started_at: run.started_at,
        finished_at: run.finished_at,
      },
    },
    findings,
  };

  return new NextResponse(JSON.stringify(report, null, 2), {
    headers: {
      "Content-Type": "application/json",
      "Content-Disposition": `attachment; filename="adcoherent-run-${run.id.slice(0, 8)}.json"`,
    },
  });
}

function csvEscape(v: unknown): string {
  const s = String(v ?? "");
  return /[",\r\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

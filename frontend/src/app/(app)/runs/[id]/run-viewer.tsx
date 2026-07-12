"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  ExternalLink,
  Flag,
  ShieldQuestion,
  Undo2,
  XCircle,
} from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { updateFindingStatus } from "@/app/actions";
import type { RunDetail } from "@/lib/data";
import type {
  AnalysisRun,
  Finding,
  FindingStatus,
  RunStatus,
  Severity,
} from "@/lib/types";
import {
  cn,
  formatCents,
  formatDateTime,
  formatTokens,
  isRunActive,
  runDuration,
  SEVERITY_STYLE,
} from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button, buttonClasses } from "@/components/ui/button";
import { LayerPipeline } from "@/components/layer-pipeline";
import {
  RunStatusBadge,
  ScanStatusBadge,
  SeverityBadge,
  VerdictBadge,
} from "@/components/badges";
import { MockAdPreview } from "./mock-ad";
import {
  DEMO_LIVE_FINDINGS,
  RUN_REACH,
  RUN_SAVINGS,
} from "@/lib/demo/fixtures";

const DEMO_SEQUENCE: RunStatus[] = [
  "running_cv",
  "running_nlp",
  "running_llm",
  "running_rules",
  "reconciling",
  "complete",
];

export function RunViewer({
  initial,
  demo,
  canReview,
}: {
  initial: RunDetail;
  demo: boolean;
  canReview: boolean;
}) {
  const [run, setRun] = useState<AnalysisRun>(initial.run);
  const [findings, setFindings] = useState<Finding[]>(initial.findings);
  const [selected, setSelected] = useState<string | null>(null);
  const [severityFilter, setSeverityFilter] = useState<Severity | "all">("all");

  // ── Live updates: Supabase Realtime (playbook Phase 7 — subscribe, don't poll)
  useEffect(() => {
    if (demo || !isRunActive(initial.run.status)) return;
    const supabase = createClient();
    const channel = supabase
      .channel(`run-${initial.run.id}`)
      .on(
        "postgres_changes",
        {
          event: "UPDATE",
          schema: "public",
          table: "analysis_runs",
          filter: `id=eq.${initial.run.id}`,
        },
        (payload) => setRun(payload.new as AnalysisRun),
      )
      .on(
        "postgres_changes",
        {
          event: "INSERT",
          schema: "public",
          table: "findings",
          filter: `run_id=eq.${initial.run.id}`,
        },
        (payload) =>
          setFindings((prev) =>
            prev.some((f) => f.id === (payload.new as Finding).id)
              ? prev
              : [...prev, payload.new as Finding],
          ),
      )
      .subscribe();
    return () => {
      void supabase.removeChannel(channel);
    };
  }, [demo, initial.run.id, initial.run.status]);

  // ── Demo mode: simulate a run progressing through the four layers.
  useEffect(() => {
    if (!demo || !isRunActive(initial.run.status)) return;
    if (initial.run.id !== RUN_SAVINGS && initial.run.status !== "queued") return;

    let i = Math.max(DEMO_SEQUENCE.indexOf(initial.run.status), 0);
    const timer = setInterval(() => {
      i += 1;
      if (i >= DEMO_SEQUENCE.length) {
        clearInterval(timer);
        return;
      }
      const status = DEMO_SEQUENCE[i];
      setRun((prev) => ({
        ...prev,
        status,
        model_id: prev.model_id ?? "claude-sonnet-5",
        ...(status === "complete"
          ? {
              finished_at: new Date().toISOString(),
              input_tokens: 51240,
              output_tokens: 2890,
              cost_cents: 58,
            }
          : {}),
      }));
      if (status === "complete" && initial.run.id === RUN_SAVINGS) {
        setFindings(DEMO_LIVE_FINDINGS);
      }
    }, 2200);
    return () => clearInterval(timer);
  }, [demo, initial.run.id, initial.run.status]);

  const shown = useMemo(
    () =>
      findings
        .filter((f) => severityFilter === "all" || f.severity === severityFilter)
        .sort(
          (a, b) =>
            severityRank(a.severity) - severityRank(b.severity) ||
            a.created_at.localeCompare(b.created_at),
        ),
    [findings, severityFilter],
  );

  const counts = useMemo(
    () => ({
      high: findings.filter((f) => f.severity === "high").length,
      medium: findings.filter((f) => f.severity === "medium").length,
      low: findings.filter((f) => f.severity === "low").length,
    }),
    [findings],
  );

  const primaryAsset = initial.assets[0];
  const demoVariant =
    run.id === RUN_REACH ? "loan" : run.id === RUN_SAVINGS ? "savings" : null;
  const imageUrl = primaryAsset ? initial.assetUrls[primaryAsset.id] : undefined;

  return (
    <>
      {/* Header */}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link
            href="/submissions"
            className="mb-2 inline-flex items-center gap-1 text-xs text-ink-faint hover:text-ink"
          >
            <ArrowLeft size={12} /> Submissions
          </Link>
          <h1 className="text-xl font-semibold tracking-tight">
            {initial.submission.title ?? "Untitled submission"}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <RunStatusBadge status={run.status} />
            {run.model_id && <Badge className="font-mono">{run.model_id}</Badge>}
            {run.rulepack_version && (
              <Badge className="font-mono">{run.rulepack_version}</Badge>
            )}
            <span className="text-[11px] text-ink-faint">
              started {formatDateTime(run.started_at ?? run.created_at)}
            </span>
          </div>
        </div>
        <div className="flex gap-2">
          <a
            href={`/api/runs/${run.id}/export?format=json`}
            className={buttonClasses("secondary", "sm")}
          >
            <Download size={13} /> JSON
          </a>
          <a
            href={`/api/runs/${run.id}/export?format=csv`}
            className={buttonClasses("secondary", "sm")}
          >
            <Download size={13} /> CSV
          </a>
        </div>
      </div>

      {/* Pipeline */}
      <Card className="mb-6">
        <CardContent className="py-5">
          <LayerPipeline status={run.status} />
          {run.status === "failed" && run.error && (
            <p className="mt-4 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {run.error}
            </p>
          )}
          {run.status === "queued" && !demo && (
            <p className="mt-4 text-[11px] text-ink-faint">
              Waiting for a worker to pick this run up. Status updates stream in
              live — no refresh needed.
            </p>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-5">
        {/* Asset panel */}
        <div className="space-y-4 lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Creative under review</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {demo && demoVariant ? (
                <MockAdPreview
                  variant={demoVariant}
                  findings={findings}
                  selectedId={selected}
                  onSelect={setSelected}
                />
              ) : imageUrl ? (
                <ImageWithOverlays
                  src={imageUrl}
                  findings={findings}
                  selectedId={selected}
                  onSelect={setSelected}
                />
              ) : (
                <p className="rounded-xl border border-dashed border-line-bright px-4 py-10 text-center text-xs text-ink-faint">
                  No visual preview for this asset type.
                </p>
              )}

              <ul className="space-y-2">
                {initial.assets.map((a) => (
                  <li
                    key={a.id}
                    className="flex flex-wrap items-center gap-2 rounded-xl border border-line bg-raised/50 px-3 py-2 text-xs"
                  >
                    <Badge className="uppercase">{a.kind}</Badge>
                    <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-ink-faint">
                      {a.source_url ?? a.storage_path ?? a.id}
                    </span>
                    <ScanStatusBadge status={a.scan_status} />
                    {a.source_url && (
                      <a
                        href={a.source_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-ink-faint hover:text-ink"
                        aria-label="Open source URL"
                      >
                        <ExternalLink size={12} />
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          {/* Provenance */}
          <Card>
            <CardHeader>
              <CardTitle>Provenance</CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-xs">
                <Prov label="Model" value={run.model_id} mono />
                <Prov label="Prompt" value={run.prompt_version} mono />
                <Prov label="Rule pack" value={run.rulepack_version} mono />
                <Prov label="Corpus hash" value={run.rag_corpus_hash} mono />
                <Prov label="Input tokens" value={formatTokens(run.input_tokens)} mono />
                <Prov label="Output tokens" value={formatTokens(run.output_tokens)} mono />
                <Prov label="Cost" value={formatCents(run.cost_cents)} mono />
                <Prov
                  label="Duration"
                  value={runDuration(run.started_at, run.finished_at)}
                  mono
                />
              </dl>
              {initial.layerOutputs.length > 0 && (
                <div className="mt-4 space-y-2">
                  {initial.layerOutputs.map((l) => (
                    <details
                      key={l.layer}
                      className="group rounded-xl border border-line bg-raised/40"
                    >
                      <summary className="cursor-pointer px-3 py-2 text-xs font-medium uppercase tracking-wider text-ink-dim hover:text-ink">
                        Layer output · {l.layer}
                      </summary>
                      <pre className="overflow-x-auto border-t border-line px-3 py-2 font-mono text-[10px] leading-relaxed text-ink-dim">
                        {JSON.stringify(l.payload, null, 2)}
                      </pre>
                    </details>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Findings */}
        <div className="lg:col-span-3">
          <Card>
            <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
              <CardTitle>
                Findings{" "}
                <span className="font-normal text-ink-faint">
                  ({findings.length})
                </span>
              </CardTitle>
              <div className="flex gap-1.5">
                {(["all", "high", "medium", "low"] as const).map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setSeverityFilter(s)}
                    className={cn(
                      "rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors",
                      severityFilter === s
                        ? s === "all"
                          ? "border-brand/40 bg-brand/10 text-brand"
                          : SEVERITY_STYLE[s]
                        : "border-line text-ink-faint hover:text-ink",
                    )}
                  >
                    {s === "all"
                      ? "All"
                      : `${s} (${counts[s]})`}
                  </button>
                ))}
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {shown.length === 0 && (
                <p className="py-12 text-center text-xs text-ink-faint">
                  {isRunActive(run.status)
                    ? "Findings appear here as the engine emits them."
                    : "No findings for this filter."}
                </p>
              )}
              {shown.map((f) => (
                <FindingCard
                  key={f.id}
                  finding={f}
                  demo={demo}
                  canReview={canReview}
                  selected={selected === f.id}
                  onSelect={() =>
                    setSelected(selected === f.id ? null : f.id)
                  }
                  onStatus={(status) =>
                    setFindings((prev) =>
                      prev.map((x) => (x.id === f.id ? { ...x, status } : x)),
                    )
                  }
                />
              ))}
              <p className="pt-2 text-center text-[10px] leading-relaxed text-ink-faint">
                AdCoherent assists review — findings are decision support, not
                legal advice. A human approves the final verdict.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

function severityRank(s: Severity) {
  return s === "high" ? 0 : s === "medium" ? 1 : 2;
}

function Prov({
  label,
  value,
  mono,
}: {
  label: string;
  value: string | null | undefined;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-ink-faint">
        {label}
      </dt>
      <dd className={cn("mt-0.5 truncate text-ink-dim", mono && "font-mono text-[11px]")}>
        {value ?? "—"}
      </dd>
    </div>
  );
}

function ImageWithOverlays({
  src,
  findings,
  selectedId,
  onSelect,
}: {
  src: string;
  findings: Finding[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  return (
    <div className="relative w-full overflow-hidden rounded-xl border border-line">
      {/* Signed URL from private storage — served off-origin by design. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt="Creative under review" className="w-full" />
      {findings
        .filter((f) => f.location?.bbox)
        .map((f) => {
          const b = f.location!.bbox!;
          const isSel = selectedId === f.id;
          return (
            <button
              key={f.id}
              type="button"
              onClick={() => onSelect(isSel ? null : f.id)}
              className={cn(
                "absolute rounded-md border-2 transition-all",
                f.severity === "high"
                  ? "border-rose-400/80"
                  : f.severity === "medium"
                    ? "border-amber-400/80"
                    : "border-sky-400/70",
                isSel ? "bg-white/10" : "hover:bg-white/5",
              )}
              style={{
                left: `${b.x * 100}%`,
                top: `${b.y * 100}%`,
                width: `${b.width * 100}%`,
                height: `${b.height * 100}%`,
              }}
              aria-label={`${f.framework} finding`}
            />
          );
        })}
    </div>
  );
}

function FindingCard({
  finding: f,
  demo,
  canReview,
  selected,
  onSelect,
  onStatus,
}: {
  finding: Finding;
  demo: boolean;
  canReview: boolean;
  selected: boolean;
  onSelect: () => void;
  onStatus: (s: FindingStatus) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(status: FindingStatus) {
    setError(null);
    if (demo) {
      onStatus(status); // local-only in demo
      return;
    }
    setBusy(true);
    const res = await updateFindingStatus(f.id, status);
    setBusy(false);
    if (!res.ok) setError(res.message);
    else onStatus(status);
  }

  return (
    <div
      className={cn(
        "rounded-2xl border p-4 transition-colors",
        selected ? "border-brand/40 bg-brand/5" : "border-line bg-raised/40",
        f.status === "dismissed" && "opacity-55",
      )}
    >
      <button
        type="button"
        onClick={onSelect}
        className="flex w-full flex-wrap items-center gap-2 text-left"
      >
        <SeverityBadge severity={f.severity} />
        <VerdictBadge verdict={f.verdict} />
        <Badge className="font-mono">{f.framework}</Badge>
        {f.rule_ref && <Badge className="font-mono">{f.rule_ref}</Badge>}
        <span className="ml-auto flex items-center gap-2">
          {f.status !== "open" && (
            <Badge
              className={cn(
                f.status === "approved" &&
                  "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
                f.status === "flagged" &&
                  "border-amber-500/30 bg-amber-500/10 text-amber-300",
              )}
            >
              {f.status}
            </Badge>
          )}
          {f.confidence != null && (
            <span
              className="font-mono text-[10px] text-ink-faint"
              title="Engine confidence"
            >
              {(f.confidence * 100).toFixed(0)}%
            </span>
          )}
        </span>
      </button>

      {f.quoted_evidence && (
        <blockquote className="mt-3 border-l-2 border-line-bright pl-3 font-mono text-[11px] leading-relaxed text-ink-dim">
          “{f.quoted_evidence}”
        </blockquote>
      )}

      <p className="mt-3 text-xs leading-relaxed text-ink-dim">{f.message}</p>

      {f.remediation && (
        <p className="mt-2.5 rounded-lg bg-canvas/70 px-3 py-2 text-xs leading-relaxed">
          <span className="font-semibold text-brand">Remediation · </span>
          <span className="text-ink-dim">{f.remediation}</span>
        </p>
      )}

      {error && (
        <p className="mt-2 text-[11px] text-rose-300">{error}</p>
      )}

      {canReview && (
        <div className="mt-3 flex flex-wrap gap-2">
          {f.status === "open" ? (
            <>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => act("approved")}
              >
                <CheckCircle2 size={13} className="text-emerald-300" /> Approve
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={busy}
                onClick={() => act("flagged")}
              >
                <Flag size={13} className="text-amber-300" /> Flag
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => act("dismissed")}
              >
                <XCircle size={13} /> Dismiss
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => act("open")}
            >
              <Undo2 size={13} /> Reopen
            </Button>
          )}
          {f.verdict === "needs_review" && f.status === "open" && (
            <span className="ml-auto flex items-center gap-1 text-[10px] text-amber-300/80">
              <ShieldQuestion size={12} /> low confidence — human call required
            </span>
          )}
        </div>
      )}
    </div>
  );
}

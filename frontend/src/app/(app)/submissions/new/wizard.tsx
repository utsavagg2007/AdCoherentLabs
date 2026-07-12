"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  FileText,
  FileUp,
  Globe,
  Loader2,
  Rocket,
  Trash2,
} from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { createSubmission, startAnalysisRun, type AssetInput } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { AssetKind, Quota } from "@/lib/types";

const KIND_BY_EXT: Record<string, AssetKind> = {
  pdf: "pdf",
  png: "image",
  jpg: "image",
  jpeg: "image",
  webp: "image",
  gif: "image",
  txt: "text",
  html: "html",
  htm: "html",
  mp4: "video",
};

const MAX_BYTES = 50 * 1024 * 1024; // bucket cap; per-tier caps live in the API

interface PendingFile {
  file: File;
  kind: AssetKind;
}

export function NewSubmissionWizard({
  orgId,
  quota,
  demo,
  canSubmit,
  frameworks,
}: {
  orgId: string;
  quota: Quota;
  demo: boolean;
  canSubmit: boolean;
  frameworks: string;
}) {
  const router = useRouter();
  const fileInput = useRef<HTMLInputElement>(null);

  const [title, setTitle] = useState("");
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [phase, setPhase] = useState<
    "idle" | "creating" | "uploading" | "starting"
  >("idle");

  const quotaBlocked = quota.remaining !== null && quota.remaining <= 0;
  const assetCount = files.length + (url.trim() ? 1 : 0);

  function addFiles(list: FileList | null) {
    if (!list) return;
    setError(null);
    const next: PendingFile[] = [];
    for (const file of Array.from(list)) {
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
      const kind = KIND_BY_EXT[ext];
      if (!kind) {
        setError(`Unsupported file type: .${ext} (pdf, png, jpg, webp, gif, txt, html, mp4)`);
        continue;
      }
      if (file.size > MAX_BYTES) {
        setError(`${file.name} exceeds the 50 MB limit.`);
        continue;
      }
      next.push({ file, kind });
    }
    setFiles((prev) => [...prev, ...next]);
  }

  async function sha256Hex(file: File): Promise<string> {
    const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
    return Array.from(new Uint8Array(digest))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }

  async function submit() {
    setError(null);
    if (demo) {
      setError("Demo mode — connect Supabase to run real analyses (README.md).");
      return;
    }
    if (!canSubmit) {
      setError("Your role (viewer) cannot submit — ask an admin for reviewer access.");
      return;
    }
    if (assetCount === 0) {
      setError("Add at least one file or a landing-page URL.");
      return;
    }

    setPhase("creating");
    const created = await createSubmission(title);
    if (!created.ok || !created.data) {
      setError(created.ok ? "Unexpected error." : created.message);
      setPhase("idle");
      return;
    }
    const { submissionId } = created.data;

    // Direct-to-storage upload under the caller's JWT: the org-scoped storage
    // policy (migration 0005) is the enforcement, path = org/submission/key.
    setPhase("uploading");
    const supabase = createClient();
    const assets: AssetInput[] = [];
    try {
      for (const { file, kind } of files) {
        const ext = file.name.split(".").pop()?.toLowerCase() ?? "bin";
        const key = crypto.randomUUID().replaceAll("-", "").slice(0, 16);
        const path = `${orgId}/${submissionId}/${key}.${ext}`;
        const { error: upErr } = await supabase.storage
          .from("assets")
          .upload(path, file, { contentType: file.type || undefined });
        if (upErr) throw new Error(`Upload failed for ${file.name}: ${upErr.message}`);
        assets.push({
          kind,
          storage_path: path,
          checksum: `sha256:${await sha256Hex(file)}`,
        });
      }
      if (url.trim()) {
        assets.push({ kind: "url", source_url: url.trim() });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase("idle");
      return;
    }

    setPhase("starting");
    const started = await startAnalysisRun(submissionId, assets);
    if (!started.ok || !started.data) {
      setError(started.ok ? "Unexpected error." : started.message);
      setPhase("idle");
      return;
    }
    router.push(`/runs/${started.data.runId}`);
  }

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        {/* Details */}
        <Card>
          <CardHeader>
            <CardTitle>1 · Submission details</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1.5">
              <Label htmlFor="title">Title</Label>
              <Input
                id="title"
                placeholder="Q3 personal-loan display campaign"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
          </CardContent>
        </Card>

        {/* Assets */}
        <Card>
          <CardHeader>
            <CardTitle>2 · Assets</CardTitle>
            <CardDescription>
              Files are malware-scanned and MIME-sniffed before analysis; URLs
              are fetched in a network-isolated sandbox.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                addFiles(e.dataTransfer.files);
              }}
              className={cn(
                "flex w-full flex-col items-center gap-2 rounded-2xl border border-dashed border-line-bright bg-raised/40 px-6 py-10",
                "text-ink-dim transition-colors hover:border-brand/50 hover:text-ink",
              )}
            >
              <FileUp size={22} className="text-brand" />
              <span className="text-sm font-medium">
                Drop creatives here or click to browse
              </span>
              <span className="text-[11px] text-ink-faint">
                PDF · PNG · JPG · WEBP · GIF · TXT · HTML · MP4 — up to 50 MB each
              </span>
            </button>
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              accept=".pdf,.png,.jpg,.jpeg,.webp,.gif,.txt,.html,.htm,.mp4"
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = "";
              }}
            />

            {files.length > 0 && (
              <ul className="space-y-2">
                {files.map((f, i) => (
                  <li
                    key={`${f.file.name}-${i}`}
                    className="flex items-center gap-3 rounded-xl border border-line bg-raised/50 px-3 py-2"
                  >
                    <FileText size={15} className="shrink-0 text-ink-faint" />
                    <span className="min-w-0 flex-1 truncate text-xs">
                      {f.file.name}
                    </span>
                    <Badge className="uppercase">{f.kind}</Badge>
                    <span className="font-mono text-[10px] text-ink-faint">
                      {(f.file.size / 1024).toFixed(0)} KB
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        setFiles((prev) => prev.filter((_, j) => j !== i))
                      }
                      className="text-ink-faint hover:text-rose-300"
                      aria-label={`Remove ${f.file.name}`}
                    >
                      <Trash2 size={14} />
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="url" className="flex items-center gap-1.5">
                <Globe size={12} /> Or analyse a landing page
              </Label>
              <Input
                id="url"
                type="url"
                placeholder="https://yourbank.com/offer"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Review & start */}
      <div>
        <Card className="sticky top-6">
          <CardHeader>
            <CardTitle>3 · Review & start</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <dl className="space-y-2.5 text-xs">
              <div className="flex justify-between">
                <dt className="text-ink-dim">Assets</dt>
                <dd className="font-mono">{assetCount}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">Reasoning model</dt>
                <dd className="font-mono">{quota.model}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="shrink-0 text-ink-dim">Frameworks</dt>
                <dd className="text-right">{frameworks}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-ink-dim">Scans remaining</dt>
                <dd className="font-mono">
                  {quota.remaining == null ? "∞" : quota.remaining}
                </dd>
              </div>
            </dl>

            <p className="rounded-lg bg-raised/60 px-3 py-2 text-[11px] leading-relaxed text-ink-faint">
              Layer 2 routes each asset to the relevant frameworks
              automatically — no manual tagging needed.
            </p>

            {error && (
              <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
                {error}
              </p>
            )}
            {quotaBlocked && (
              <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
                Monthly scan quota reached — upgrade on the Billing page to
                continue.
              </p>
            )}

            <Button
              className="w-full"
              disabled={phase !== "idle" || quotaBlocked || assetCount === 0}
              onClick={submit}
            >
              {phase === "idle" ? (
                <>
                  <Rocket size={15} /> Start analysis
                </>
              ) : (
                <>
                  <Loader2 size={15} className="animate-spin" />
                  {phase === "creating"
                    ? "Creating submission…"
                    : phase === "uploading"
                      ? "Uploading assets…"
                      : "Enqueueing run…"}
                </>
              )}
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

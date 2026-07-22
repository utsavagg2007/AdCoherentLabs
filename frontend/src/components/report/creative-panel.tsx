"use client";

/** Creative preview: signed-URL asset previews (user session, RLS-scoped)
 * with an optional detected-region overlay from finding bounding boxes. */

import { useEffect, useState } from "react";
import { ExternalLink, FileText, Frame, ImageOff } from "lucide-react";
import { useApi, useOrg } from "@/components/providers";
import { Skeleton } from "@/components/ui/feedback";
import { extractBox, type FoundBox } from "@/lib/bbox";
import { useAsyncData } from "@/lib/hooks";
import { signedAssetUrl } from "@/lib/supabase";
import type { FindingRow, Severity } from "@/lib/types";
import { cn } from "@/lib/utils";

interface OverlayBox extends FoundBox {
  severity: Severity;
  index: number;
}

const SEVERITY_BORDER: Record<Severity, string> = {
  high: "border-red-500/90",
  medium: "border-amber-500/90",
  low: "border-emerald-500/90",
};
const SEVERITY_TAG: Record<Severity, string> = {
  high: "bg-red-500",
  medium: "bg-amber-500",
  low: "bg-emerald-500",
};

function AssetImage({
  path,
  boxes,
  showBoxes,
}: {
  path: string;
  boxes: OverlayBox[];
  showBoxes: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    signedAssetUrl(path).then((u) => {
      if (!cancelled) {
        setUrl(u);
        if (!u) setFailed(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [path]);

  if (failed) {
    return (
      <div className="flex aspect-video items-center justify-center rounded-xl border border-line bg-cream text-ink-500">
        <div className="text-center">
          <ImageOff className="mx-auto size-6" aria-hidden />
          <p className="mt-2 text-[12px]">
            Preview unavailable — the signed URL could not be issued.
          </p>
        </div>
      </div>
    );
  }
  if (!url) return <Skeleton className="aspect-video w-full" />;

  return (
    <div className="relative overflow-hidden rounded-xl border border-line bg-coal-800">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={url}
        alt="Submitted creative"
        className="block w-full"
        onLoad={(e) =>
          setNatural({
            w: e.currentTarget.naturalWidth,
            h: e.currentTarget.naturalHeight,
          })
        }
        onError={() => setFailed(true)}
      />
      {showBoxes &&
        natural &&
        boxes.map((b) => {
          const left = b.normalized ? b.x * 100 : (b.x / natural.w) * 100;
          const top = b.normalized ? b.y * 100 : (b.y / natural.h) * 100;
          const width = b.normalized ? b.w * 100 : (b.w / natural.w) * 100;
          const height = b.normalized ? b.h * 100 : (b.h / natural.h) * 100;
          if (width <= 0 || height <= 0 || left > 100 || top > 100) return null;
          return (
            <div
              key={b.index}
              className={cn(
                "pointer-events-none absolute rounded-sm border-2",
                SEVERITY_BORDER[b.severity]
              )}
              style={{
                left: `${left}%`,
                top: `${top}%`,
                width: `${Math.min(width, 100 - left)}%`,
                height: `${Math.min(height, 100 - top)}%`,
              }}
            >
              <span
                className={cn(
                  "absolute -top-5 left-0 rounded-sm px-1 py-px text-[9.5px] font-bold text-white",
                  SEVERITY_TAG[b.severity]
                )}
              >
                F{b.index + 1}
              </span>
            </div>
          );
        })}
    </div>
  );
}

function AssetText({ path }: { path: string }) {
  const [content, setContent] = useState<string | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const u = await signedAssetUrl(path);
      if (cancelled) return;
      setUrl(u);
      if (!u) {
        setFailed(true);
        return;
      }
      try {
        const res = await fetch(u);
        const text = await res.text();
        if (!cancelled) setContent(text.slice(0, 20000));
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [path]);

  if (failed) {
    return (
      <p className="rounded-xl border border-line bg-cream p-4 text-[12.5px] text-ink-500">
        The source file preview is unavailable right now.
      </p>
    );
  }
  if (content === null) return <Skeleton className="h-40 w-full" />;

  return (
    <div>
      {/* rendered as plain text — never as markup */}
      <pre className="max-h-72 overflow-auto rounded-xl border border-line bg-cream/70 p-4 text-[12px] leading-relaxed break-words whitespace-pre-wrap text-ink-800">
        {content}
      </pre>
      {url && (
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-flex items-center gap-1 text-[12px] font-bold text-ink-900 hover:text-white"
        >
          Open source file
          <ExternalLink className="size-3" aria-hidden />
        </a>
      )}
    </div>
  );
}

export function CreativePanel({
  submissionId,
  findings,
}: {
  submissionId: string;
  findings: FindingRow[];
}) {
  const api = useApi();
  const { orgId } = useOrg();
  const [showBoxes, setShowBoxes] = useState(true);
  const detail = useAsyncData(
    (s) => api.getSubmission(submissionId, s),
    [api, orgId, submissionId]
  );

  const boxes: OverlayBox[] = findings.flatMap((f, i) => {
    const box = extractBox(f.location);
    return box ? [{ ...box, severity: f.severity, index: i }] : [];
  });

  const assets = detail.data?.assets ?? [];
  const imageAssets = assets.filter((a) => a.kind === "image");
  const overlayEligible = imageAssets.length === 1 && boxes.length > 0;

  return (
    <section aria-label="Creative" className="card p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
          Creative
        </h2>
        {overlayEligible && (
          <button
            type="button"
            onClick={() => setShowBoxes((s) => !s)}
            aria-pressed={showBoxes}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11.5px] font-bold transition-colors",
              showBoxes
                ? "border-white/20 bg-white/6 text-ink-850"
                : "border-line bg-coal-800 text-ink-500 hover:text-ink-900"
            )}
          >
            <Frame className="size-3.5" aria-hidden />
            {showBoxes ? "Regions on" : "Regions off"}
          </button>
        )}
      </div>

      <div className="mt-3 space-y-3">
        {detail.loading && <Skeleton className="aspect-video w-full" />}
        {!detail.loading && assets.length === 0 && (
          <div className="rounded-xl border border-line bg-cream/70 p-4">
            <p className="flex items-center gap-2 text-[12.5px] font-semibold text-ink-500">
              <FileText className="size-4" aria-hidden />
              Inline submission — the reviewed content is quoted in the
              findings below.
            </p>
          </div>
        )}
        {imageAssets.map((a, i) => (
          <div key={a.id}>
            {imageAssets.length > 1 && (
              <p className="mb-1 font-mono text-[10.5px] font-bold text-ink-500">
                CARD {String(i + 1).padStart(2, "0")}
              </p>
            )}
            <AssetImage
              path={a.storage_path}
              boxes={overlayEligible ? boxes : []}
              showBoxes={showBoxes && overlayEligible}
            />
          </div>
        ))}
        {assets
          .filter((a) => a.kind !== "image")
          .map((a) => (
            <AssetText key={a.id} path={a.storage_path} />
          ))}
        {detail.data?.submission.title && (
          <p className="text-[12px] text-ink-500">
            “{detail.data.submission.title}”
            {detail.data.submission.target_jurisdictions?.length
              ? ` · ${detail.data.submission.target_jurisdictions.join(", ")}`
              : ""}
          </p>
        )}
      </div>
    </section>
  );
}

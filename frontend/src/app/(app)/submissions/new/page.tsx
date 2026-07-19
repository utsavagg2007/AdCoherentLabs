"use client";

/** The compliance workbench: upload / carousel / paste text / paste HTML.
 * Client-side guidance only — the backend owns validation, scanning, storage,
 * charging, and enqueueing. One Idempotency-Key per distinct payload, reused
 * verbatim on retries; never silently rotated. */

import { useRouter } from "next/navigation";
import { useCallback, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  CircleDollarSign,
  Code2,
  GalleryHorizontalEnd,
  ImageUp,
  Type,
} from "lucide-react";
import { PageBody, PageHeader } from "@/components/app/page-header";
import { CREDITS_REFRESH_EVENT } from "@/components/app/sidebar";
import { Dropzone, buildPicked, type PickedFile } from "@/components/app/dropzone";
import { JurisdictionSelect } from "@/components/app/jurisdiction-select";
import { useApi, useOrg } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Disclaimer, ErrorPanel } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { isApiError } from "@/lib/api";
import { useAsyncData } from "@/lib/hooks";
import type { PriceList } from "@/lib/types";
import { cn, formatNumber, newIdempotencyKey } from "@/lib/utils";

type Mode = "upload" | "carousel" | "text" | "html";

const MODES: { id: Mode; label: string; icon: React.ElementType }[] = [
  { id: "upload", label: "Upload", icon: ImageUp },
  { id: "carousel", label: "Carousel", icon: GalleryHorizontalEnd },
  { id: "text", label: "Paste text", icon: Type },
  { id: "html", label: "Paste HTML", icon: Code2 },
];

function inlineKindForFile(f: File): "image" | "text" | "html" {
  if (f.type.startsWith("image/")) return "image";
  if (f.type === "text/html" || /\.html?$/i.test(f.name)) return "html";
  return "text";
}

export default function NewSubmissionPage() {
  const api = useApi();
  const { orgId } = useOrg();
  const router = useRouter();
  const { toast } = useToast();

  const credits = useAsyncData((s) => api.credits(s), [api, orgId]);
  const orgMe = useAsyncData((s) => api.orgMe(s), [api, orgId]);
  const capMb = orgMe.data?.entitlements.max_upload_mb ?? null;

  const [mode, setMode] = useState<Mode>("upload");
  const [files, setFiles] = useState<PickedFile[]>([]);
  const [cards, setCards] = useState<PickedFile[]>([]);
  const [text, setText] = useState("");
  const [html, setHtml] = useState("");
  const [title, setTitle] = useState("");
  const [jurisdictions, setJurisdictions] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  // idempotency: one key per distinct payload, kept across retries
  const idemRef = useRef<{ fingerprint: string; key: string } | null>(null);

  const priceList: PriceList = useMemo(
    () => credits.data?.price_list ?? {},
    [credits.data]
  );
  const balance = credits.data?.total ?? null;

  const activeFiles = useMemo(
    () => (mode === "upload" ? files : mode === "carousel" ? cards : []),
    [mode, files, cards]
  );

  const estimate = useMemo(() => {
    const p = priceList;
    if (mode === "text") return text.trim() ? (p.text ?? null) : null;
    if (mode === "html") return html.trim() ? (p.html ?? null) : null;
    if (mode === "upload") {
      if (files.length !== 1) return null;
      const kind = inlineKindForFile(files[0].file);
      return p[kind] ?? null;
    }
    if (mode === "carousel") {
      if (cards.length < 1) return null;
      if (cards.length === 1) return p.image ?? null;
      if (p.image == null || p.carousel_card == null) return null;
      return p.image + (cards.length - 1) * p.carousel_card;
    }
    return null;
  }, [mode, text, html, files, cards, priceList]);

  const blockingProblem = useMemo(() => {
    if (mode === "upload") {
      if (files.length === 0) return "Add a creative to review.";
      if (files[0].unsupported)
        return "This file type isn't analyzable in v1 — use PNG, JPEG, WebP, GIF, TXT, or HTML.";
      if (files[0].overCap)
        return `This file is over your plan's ${capMb} MB upload cap.`;
    }
    if (mode === "carousel") {
      if (cards.length === 0) return "Add 2–10 image cards.";
      if (cards.length < 2) return "A carousel needs at least 2 cards — use Upload for a single image.";
      if (cards.some((c) => c.unsupported)) return "Carousel cards must be images (PNG, JPEG, WebP, GIF).";
      if (cards.some((c) => c.overCap)) return `Every card must be within the ${capMb} MB upload cap.`;
    }
    if (mode === "text" && !text.trim()) return "Paste the ad copy to review.";
    if (mode === "html" && !html.trim()) return "Paste the ad HTML to review.";
    return null;
  }, [mode, files, cards, text, html, capMb]);

  const ready = blockingProblem === null;

  const fingerprint = useMemo(() => {
    const filesSig = activeFiles
      .map((f) => `${f.file.name}:${f.file.size}:${f.file.lastModified}`)
      .join("|");
    const content =
      mode === "text" ? text : mode === "html" ? html : filesSig;
    return JSON.stringify({
      mode,
      title,
      jurisdictions,
      len: content.length,
      head: content.slice(0, 64),
      tail: content.slice(-64),
    });
  }, [mode, title, jurisdictions, text, html, activeFiles]);

  const addFiles = useCallback(
    (incoming: File[], target: "upload" | "carousel") => {
      const picked = incoming.map((f) => buildPicked(f, capMb));
      if (target === "upload") {
        setFiles(picked.slice(0, 1));
      } else {
        setCards((prev) => [...prev, ...picked].slice(0, 10));
      }
    },
    [capMb]
  );

  async function submit() {
    if (!ready || submitting) return;
    // reuse the key for an identical retry; mint a new one only when the
    // payload itself changed
    if (!idemRef.current || idemRef.current.fingerprint !== fingerprint) {
      idemRef.current = { fingerprint, key: newIdempotencyKey() };
    }
    const key = idemRef.current.key;
    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        title: title.trim() || undefined,
        target_jurisdictions: jurisdictions,
      };
      const accepted =
        mode === "text"
          ? await api.submitInline({ kind: "text", content: text, ...payload }, key)
          : mode === "html"
            ? await api.submitInline({ kind: "html", content: html, ...payload }, key)
            : await api.submitFiles(
                { files: activeFiles.map((f) => f.file), ...payload },
                key
              );
      idemRef.current = null;
      window.dispatchEvent(new Event(CREDITS_REFRESH_EVENT));
      toast({
        kind: "success",
        title: `Review started — ${accepted.credits_charged} credit${accepted.credits_charged === 1 ? "" : "s"} charged`,
        detail: `Balance: ${formatNumber(accepted.balance.subscription_credits + accepted.balance.purchased_credits)} credits remaining.`,
      });
      router.push(`/runs/${accepted.run_id}`);
    } catch (e) {
      setConfirming(false);
      setError(e);
      setSubmitting(false);
    }
  }

  const insufficient =
    isApiError(error) && error.status === 402 ? error : null;

  return (
    <>
      <PageHeader
        title="New review"
        description="Submit one creative — the four-layer review returns findings with quoted evidence and citations."
      />
      <PageBody>
        <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
          {/* -------- workbench -------- */}
          <div className="min-w-0 space-y-6">
            <Tabs
              value={mode}
              onValueChange={(v) => {
                setMode(v as Mode);
                setError(null);
              }}
            >
              <TabsList label="Input mode">
                {MODES.map((m) => {
                  const Icon = m.icon;
                  return (
                    <TabsTrigger key={m.id} value={m.id}>
                      <span className="inline-flex items-center gap-1.5">
                        <Icon className="size-3.5" aria-hidden />
                        {m.label}
                      </span>
                    </TabsTrigger>
                  );
                })}
              </TabsList>

              <div className="mt-5">
                {mode === "upload" && (
                  <Dropzone
                    files={files}
                    onAdd={(f) => addFiles(f, "upload")}
                    onRemove={(id) => setFiles((p) => p.filter((f) => f.id !== id))}
                    multiple={false}
                    maxFiles={1}
                    capMb={capMb}
                  />
                )}
                {mode === "carousel" && (
                  <div>
                    <Dropzone
                      files={cards}
                      onAdd={(f) => addFiles(f, "carousel")}
                      onRemove={(id) => setCards((p) => p.filter((f) => f.id !== id))}
                      multiple
                      maxFiles={10}
                      capMb={capMb}
                      imagesOnly
                    />
                    <p className="mt-2 text-[12px] text-zinc-400">
                      {cards.length}/10 cards · reviewed as one submission, in
                      this order.
                    </p>
                  </div>
                )}
                {mode === "text" && (
                  <div>
                    <label htmlFor="ad-text" className="label">
                      Ad copy
                    </label>
                    <textarea
                      id="ad-text"
                      className="input min-h-56 resize-y leading-relaxed"
                      placeholder={
                        "Paste the full ad copy — headline, body, offer terms, and any fine print…"
                      }
                      value={text}
                      onChange={(e) => setText(e.target.value)}
                      maxLength={2_000_000}
                    />
                    <p className="mt-1.5 text-right text-[11.5px] text-zinc-400 tabular-nums">
                      {formatNumber(text.length)} characters
                    </p>
                  </div>
                )}
                {mode === "html" && (
                  <div>
                    <label htmlFor="ad-html" className="label">
                      Ad HTML
                    </label>
                    <textarea
                      id="ad-html"
                      className="input min-h-56 resize-y font-mono text-[12.5px] leading-relaxed"
                      placeholder={`<div class="ad">\n  <h1>Your headline</h1>\n  …\n</div>`}
                      value={html}
                      onChange={(e) => setHtml(e.target.value)}
                      maxLength={2_000_000}
                      spellCheck={false}
                    />
                    <p className="mt-1.5 text-right text-[11.5px] text-zinc-400 tabular-nums">
                      {formatNumber(html.length)} characters
                    </p>
                  </div>
                )}
              </div>
            </Tabs>

            <div className="grid gap-5 sm:grid-cols-2">
              <div>
                <label htmlFor="title" className="label">
                  Title <span className="font-normal text-zinc-400">(optional)</span>
                </label>
                <input
                  id="title"
                  className="input"
                  placeholder="Q3 personal-loan banner"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  maxLength={300}
                />
              </div>
              <div>
                <span className="label">
                  Target jurisdictions{" "}
                  <span className="font-normal text-zinc-400">(optional)</span>
                </span>
                <JurisdictionSelect
                  selected={jurisdictions}
                  onChange={setJurisdictions}
                />
              </div>
            </div>

            {error != null && !insufficient ? (
              <ErrorPanel error={error} onRetry={() => setConfirming(true)} />
            ) : null}
            {insufficient && (
              <div role="alert" className="rounded-2xl border border-amber-300 bg-amber-50 p-5">
                <p className="text-sm font-bold text-amber-900">
                  Not enough credits for this review
                </p>
                <p className="mt-1 text-[13px] leading-relaxed text-amber-800">
                  It costs{" "}
                  <strong>{String(insufficient.details["needed"] ?? "—")}</strong>{" "}
                  credits and your balance is{" "}
                  <strong>{String(insufficient.details["balance"] ?? "—")}</strong>.
                  Nothing was charged. Add a credit pack or upgrade to continue.
                </p>
                <div className="mt-3 flex gap-2.5">
                  <Button href="/billing" size="sm">
                    <CircleDollarSign className="size-4" aria-hidden />
                    Get credits
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => setError(null)}>
                    Dismiss
                  </Button>
                </div>
              </div>
            )}
          </div>

          {/* -------- summary rail -------- */}
          <aside className="xl:sticky xl:top-6 xl:self-start">
            <div className="card p-5">
              <h2 className="text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
                Review summary
              </h2>
              <dl className="mt-4 space-y-2.5 text-[13px]">
                <div className="flex justify-between gap-3">
                  <dt className="text-zinc-500">Input</dt>
                  <dd className="font-bold text-ink-900">
                    {mode === "upload"
                      ? files.length
                        ? files[0].file.type.startsWith("image/")
                          ? "Image"
                          : inlineKindForFile(files[0].file) === "html"
                            ? "HTML file"
                            : "Text file"
                        : "—"
                      : mode === "carousel"
                        ? cards.length
                          ? `Carousel · ${cards.length} cards`
                          : "—"
                        : mode === "text"
                          ? "Pasted text"
                          : "Pasted HTML"}
                  </dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-zinc-500">Jurisdictions</dt>
                  <dd className="font-bold text-ink-900">
                    {jurisdictions.length === 0
                      ? "Nationwide"
                      : jurisdictions.join(", ")}
                  </dd>
                </div>
                <div className="flex justify-between gap-3 border-t border-line pt-2.5">
                  <dt className="text-zinc-500">Estimated cost</dt>
                  <dd className="text-lg font-extrabold text-violet-700 tabular-nums">
                    {estimate !== null ? `${estimate} credits` : "—"}
                  </dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-zinc-500">Balance</dt>
                  <dd className="font-bold text-ink-900 tabular-nums">
                    {balance !== null ? formatNumber(balance) : "—"}
                    {estimate !== null && balance !== null && (
                      <span className="ml-1 text-[11.5px] font-semibold text-zinc-400">
                        → {formatNumber(Math.max(0, balance - estimate))}
                      </span>
                    )}
                  </dd>
                </div>
              </dl>
              {credits.data && (
                <p className="mt-3 rounded-lg bg-cream p-2.5 text-[11.5px] leading-relaxed text-zinc-500">
                  Your {credits.data.tier} plan prices: text{" "}
                  {priceList.text ?? "—"} · image {priceList.image ?? "—"} ·
                  HTML {priceList.html ?? "—"} · extra card{" "}
                  {priceList.carousel_card ?? "—"}. The charge is confirmed
                  before anything runs.
                </p>
              )}
              <Button
                className="mt-4 w-full"
                size="lg"
                disabled={!ready || estimate === null}
                onClick={() => setConfirming(true)}
              >
                Review charge
                <ArrowRight className="size-4" aria-hidden />
              </Button>
              <p
                className={cn(
                  "mt-2.5 text-center text-[12px] leading-relaxed",
                  ready ? "text-zinc-400" : "font-semibold text-amber-700"
                )}
                role={ready ? undefined : "status"}
              >
                {blockingProblem ??
                  "Uploads are scanned and re-encoded before analysis."}
              </p>
            </div>
            <Disclaimer className="mt-3 px-1" />
          </aside>
        </div>
      </PageBody>

      {/* charge confirmation */}
      <Dialog open={confirming} onOpenChange={(o) => !submitting && setConfirming(o)}>
        <DialogContent
          title="Confirm this review"
          description="Credits are charged when the run is accepted."
        >
          <div className="rounded-xl border border-line bg-cream/70 p-4">
            <div className="flex items-baseline justify-between">
              <span className="text-sm font-semibold text-zinc-600">
                This review will charge
              </span>
              <span className="text-2xl font-extrabold text-violet-700 tabular-nums">
                {estimate ?? "—"} credits
              </span>
            </div>
            <p className="mt-1.5 text-[12.5px] leading-relaxed text-zinc-500">
              {mode === "carousel"
                ? `Image cost plus ${Math.max(0, cards.length - 1)} additional card${cards.length - 1 === 1 ? "" : "s"}.`
                : "Priced from your plan's live price list."}{" "}
              If the run fails on our side, credits are refunded automatically.
            </p>
          </div>
          <div className="mt-5 flex justify-end gap-2.5">
            <Button
              variant="secondary"
              onClick={() => setConfirming(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button onClick={submit} loading={submitting}>
              Charge {estimate ?? "—"} credits & run
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

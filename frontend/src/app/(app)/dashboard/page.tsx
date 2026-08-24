"use client";

/**
 * The review console — one conversation, one creative.
 *
 * This replaces the old form-shaped workbench (mode tabs, a price quote, and a
 * "Charge N credits & run" button). A compliance review is a documented
 * exchange, so it is rendered as a record: you send the creative, the console
 * asks the two things that change what gets checked, the engine works in the
 * open, and its own questions come back in the same thread.
 *
 * Cost appears nowhere. Credits are still metered server-side against the run's
 * escrow; the product decision is that the reviewer should be thinking about
 * the ad, not the meter.
 *
 * Reload safety: the run id lives in `?run=`, and everything above it is
 * rebuilt from the submission and the run's own `operator_guidance`. The
 * transcript is a view of the audit trail, not state that only exists here.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { FileText, Layers, MapPin, ShieldCheck, Sparkles } from "lucide-react";
import { Composer, describeDraft, type Draft } from "@/components/chat/composer";
import {
  JurisdictionQuestion,
  SubstantiationQuestion,
} from "@/components/chat/intake";
import { RunThread } from "@/components/chat/run-thread";
import { Transcript, Turn, TurnCard } from "@/components/chat/turn";
import { useApi, useOrg } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { Disclaimer, PageLoading } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import { isApiError } from "@/lib/api";
import { spotClaims, type SpottedClaim } from "@/lib/claims";
import { useAsyncData } from "@/lib/hooks";
import { US_JURISDICTIONS } from "@/lib/jurisdictions";
import { newIdempotencyKey, truncate } from "@/lib/utils";

/** What the "You" turn shows for the creative — never the raw File object. */
interface CreativeSummary {
  label: string;
  excerpt: string | null;
  at: string;
}

export default function ReviewConsolePage() {
  return (
    <Suspense fallback={<PageLoading label="Opening the review console" />}>
      <Console />
    </Suspense>
  );
}

function Console() {
  const api = useApi();
  const { orgId } = useOrg();
  const router = useRouter();
  const params = useSearchParams();
  const { toast } = useToast();

  const urlRun = params.get("run");

  const orgMe = useAsyncData((s) => api.orgMe(s), [api, orgId]);
  const ent = orgMe.data?.entitlements;

  // -- conversation state ---------------------------------------------------
  const [creative, setCreative] = useState<CreativeSummary | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [claims, setClaims] = useState<SpottedClaim[]>([]);
  const [jurisdictions, setJurisdictions] = useState<string[] | null>(null);
  /** undefined = not asked yet, null = explicitly skipped. */
  const [substantiation, setSubstantiation] = useState<string | null | undefined>(
    undefined
  );
  const [runIds, setRunIds] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [rejected, setRejected] = useState<string | null>(null);

  // Idempotency: one key per distinct payload, reused verbatim on retry.
  const idemRef = useRef<{ fingerprint: string; key: string } | null>(null);
  // Guards the one-shot rebuild below without re-reading state during render.
  const restoredRef = useRef<string | null>(null);

  // -- restore from ?run= ---------------------------------------------------
  const restore = useCallback(
    async (runId: string) => {
      try {
        const rr = await api.getRun(runId);
        const sub = await api.getSubmission(rr.run.submission_id);
        const kind = String(sub.submission.params?.pricing_kind ?? "text");
        const cards = Number(sub.submission.params?.cards ?? 1);
        setCreative({
          label:
            cards > 1
              ? `Carousel · ${cards} cards`
              : sub.submission.title || KIND_TEXT[kind] || "Creative",
          excerpt: null,
          at: sub.submission.created_at,
        });
        setJurisdictions(sub.submission.target_jurisdictions ?? []);
        setSubstantiation(rr.run.operator_guidance);
        setRunIds([runId]);
      } catch {
        // A stale or foreign run id: drop it and start clean rather than
        // stranding the user on a console that renders nothing.
        router.replace("/dashboard");
      }
    },
    [api, router]
  );

  useEffect(() => {
    if (!urlRun || restoredRef.current === urlRun) return;
    restoredRef.current = urlRun;
    void restore(urlRun);
  }, [urlRun, restore]);

  // -- actions --------------------------------------------------------------
  function acceptDraft(d: Draft) {
    const now = new Date().toISOString();
    if (d.mode === "files") {
      const many = d.files.length > 1;
      setCreative({
        label: describeDraft(d),
        excerpt: many
          ? d.files.map((f) => f.file.name).join(", ")
          : (d.files[0]?.file.name ?? null),
        at: now,
      });
      setClaims([]); // no client-side text to read; Layer 2 finds the claims
    } else {
      setCreative({
        label: describeDraft(d),
        excerpt: truncate(d.text.replace(/\s+/g, " ").trim(), 260),
        at: now,
      });
      setClaims(spotClaims(d.text));
    }
    setDraft(d);
    setJurisdictions(null);
    setSubstantiation(undefined);
    setRejected(null);
  }

  async function submit(codes: string[], backing: string | null) {
    if (!draft || submitting) return;
    const fingerprint = JSON.stringify({
      mode: draft.mode,
      codes,
      backing,
      body:
        draft.mode === "files"
          ? draft.files.map((f) => `${f.file.name}:${f.file.size}`).join("|")
          : `${draft.text.length}:${draft.text.slice(0, 64)}`,
    });
    if (!idemRef.current || idemRef.current.fingerprint !== fingerprint) {
      idemRef.current = { fingerprint, key: newIdempotencyKey() };
    }
    setSubmitting(true);
    setRejected(null);
    try {
      const payload = {
        target_jurisdictions: codes,
        ...(backing ? { substantiation: backing } : {}),
      };
      const accepted =
        draft.mode === "files"
          ? await api.submitFiles(
              { files: draft.files.map((f) => f.file), ...payload },
              idemRef.current.key
            )
          : await api.submitInline(
              { kind: draft.mode, content: draft.text, ...payload },
              idemRef.current.key
            );
      idemRef.current = null;
      setRunIds([accepted.run_id]);
      restoredRef.current = accepted.run_id;
      router.replace(`/dashboard?run=${accepted.run_id}`);
    } catch (e) {
      if (isApiError(e) && e.status === 402) {
        setRejected(e.message);
      } else {
        toast({
          kind: "error",
          title: "Couldn't start the review",
          detail: isApiError(e) ? e.message : "Try again in a moment.",
        });
      }
    } finally {
      setSubmitting(false);
    }
  }

  function reset() {
    setCreative(null);
    setDraft(null);
    setClaims([]);
    setJurisdictions(null);
    setSubstantiation(undefined);
    setRunIds([]);
    setRejected(null);
    restoredRef.current = null;
    idemRef.current = null;
    router.replace("/dashboard");
  }

  const asking =
    creative !== null &&
    runIds.length === 0 &&
    (jurisdictions === null || substantiation === undefined);
  const started = runIds.length > 0;

  return (
    // -mb-16 cancels the app shell's pb-16 so the composer can sit flush.
    <div className="-mb-16 flex min-h-[calc(100dvh-3.5rem)] flex-col lg:min-h-dvh">
      <ConsoleHeader
        subject={creative?.label ?? null}
        jurisdictions={jurisdictions}
        onReset={started ? reset : undefined}
      />

      <div className="flex-1">
        <Transcript>
          {creative === null ? (
            <EmptyState />
          ) : (
            <>
              <Turn role="you" at={creative.at} className="chat-turn-enter">
                <p className="font-semibold text-strong">{creative.label}</p>
                {creative.excerpt && (
                  <p className="mt-2 border-l-2 border-line-strong pl-3 text-[13.5px] leading-relaxed text-muted">
                    {creative.excerpt}
                  </p>
                )}
              </Turn>

              {/* Q1 — jurisdictions */}
              <Turn role="assistant" at={creative.at} className="chat-turn-enter">
                {jurisdictions === null ? (
                  <JurisdictionQuestion onAnswer={setJurisdictions} />
                ) : (
                  <p>
                    Before I start — where will this run?
                  </p>
                )}
              </Turn>
              {jurisdictions !== null && (
                <Turn role="you" at={creative.at} className="chat-turn-enter">
                  <p className="flex items-center gap-2">
                    <MapPin className="size-4 shrink-0 text-subtle" aria-hidden />
                    {jurisdictions.length === 0
                      ? "Nationwide — no state targeting."
                      : jurisdictions.map(stateName).join(", ")}
                  </p>
                </Turn>
              )}

              {/* Q2 — substantiation */}
              {jurisdictions !== null && (
                <Turn role="assistant" at={creative.at} className="chat-turn-enter">
                  {substantiation === undefined ? (
                    <SubstantiationQuestion
                      claims={claims}
                      onAnswer={(v) => {
                        setSubstantiation(v);
                        void submit(jurisdictions, v);
                      }}
                    />
                  ) : (
                    <p>
                      {claims.length > 0
                        ? "And what supports the claims in it?"
                        : "Is there evidence I should review alongside this?"}
                    </p>
                  )}
                </Turn>
              )}
              {substantiation !== undefined && (
                <Turn role="you" at={creative.at} className="chat-turn-enter">
                  {substantiation ? (
                    <p className="whitespace-pre-wrap">{substantiation}</p>
                  ) : (
                    <p className="text-subtle">
                      Nothing to add — reviewing the creative on its own.
                    </p>
                  )}
                </Turn>
              )}

              {rejected && (
                <Turn role="assistant" at={new Date()}>
                  <p>I couldn&apos;t start this one.</p>
                  <TurnCard tone="warn">
                    <p className="text-[13.5px] leading-relaxed text-warn">
                      {rejected}
                    </p>
                    <div className="mt-4">
                      <Button size="sm" href="/billing">
                        Review your plan
                      </Button>
                    </div>
                  </TurnCard>
                </Turn>
              )}

              {runIds.map((id) => (
                <RunThread
                  key={id}
                  runId={id}
                  onResumed={(next) =>
                    setRunIds((prev) =>
                      prev.includes(next) ? prev : [...prev, next]
                    )
                  }
                />
              ))}
            </>
          )}
        </Transcript>
      </div>

      {/* -- composer ---------------------------------------------------- */}
      <div className="glass sticky bottom-0 z-30 border-t border-line pt-3 pb-4">
        <div className="mx-auto w-full max-w-[52rem] px-4 sm:px-6">
          {started ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-line bg-raised px-4 py-3">
              <p className="text-[13px] text-subtle">
                This conversation is one review. Start another to send a new
                creative.
              </p>
              <Button size="sm" variant="secondary" onClick={reset}>
                <Sparkles className="size-4" aria-hidden />
                New review
              </Button>
            </div>
          ) : (
            <Composer
              onSubmit={acceptDraft}
              disabled={asking || submitting}
              busy={submitting}
              autoFocus
              capMb={ent?.max_upload_mb ?? null}
              allowedKinds={ent?.allowed_kinds ?? null}
              maxVideoSeconds={ent?.max_video_seconds ?? null}
              placeholder={
                asking
                  ? "Answer above to start the review…"
                  : "Paste the ad copy, or drop the creative here."
              }
            />
          )}
          <Disclaimer className="mt-2.5 px-1" />
        </div>
      </div>
    </div>
  );
}

function ConsoleHeader({
  subject,
  jurisdictions,
  onReset,
}: {
  subject: string | null;
  jurisdictions: string[] | null;
  onReset?: () => void;
}) {
  return (
    <header className="glass sticky top-0 z-30 border-b border-line">
      <div className="mx-auto flex w-full max-w-[52rem] items-center justify-between gap-4 px-4 py-3.5 sm:px-6">
        <div className="min-w-0">
          <h1 className="truncate text-[15px] font-extrabold text-strong">
            {subject ?? "New review"}
          </h1>
          <p className="truncate text-[12px] text-subtle">
            {jurisdictions === null
              ? "Four-layer compliance review"
              : jurisdictions.length === 0
                ? "Nationwide · federal frameworks"
                : `${jurisdictions.length} state${jurisdictions.length === 1 ? "" : "s"} · federal + state UDAP`}
          </p>
        </div>
        {onReset && (
          <Button size="sm" variant="ghost" onClick={onReset}>
            New review
          </Button>
        )}
      </div>
    </header>
  );
}

function EmptyState() {
  return (
    <div className="py-14 sm:py-20">
      <h2 className="font-display text-2xl font-extrabold text-strong sm:text-3xl">
        What are we reviewing?
      </h2>
      <p className="mt-2 max-w-lg text-[14.5px] leading-relaxed text-muted">
        Send the creative and I&apos;ll check it against the regulatory
        frameworks that apply, quote the evidence for every finding, and cite
        the rule behind it.
      </p>
      <ul className="mt-8 space-y-3.5">
        {[
          {
            icon: FileText,
            text: "Paste ad copy or HTML straight into the box below.",
          },
          {
            icon: Layers,
            text: "Or drop an image, PDF, Word document, or video — several images become a carousel.",
          },
          {
            icon: ShieldCheck,
            text: "I'll ask where it runs and what backs your claims before starting.",
          },
        ].map(({ icon: Icon, text }) => (
          <li key={text} className="flex items-start gap-3">
            <Icon className="mt-0.5 size-4 shrink-0 text-brand" aria-hidden />
            <span className="text-[13.5px] leading-relaxed text-muted">
              {text}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const KIND_TEXT: Record<string, string> = {
  text: "Pasted text",
  html: "Pasted HTML",
  image: "Image",
  carousel: "Carousel",
  pdf: "PDF",
  docx: "Word document",
  video: "Video",
};

function stateName(code: string): string {
  return US_JURISDICTIONS.find((j) => j.code === code)?.name ?? code;
}

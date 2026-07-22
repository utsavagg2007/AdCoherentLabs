"use client";

import { useEffect, useRef, useState } from "react";
import {
  Activity,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Loader2,
} from "lucide-react";
import { usePrefersReducedMotion } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/** "Watch it think" — a faithful demo of the in-app live activity feed.
 * Timer-driven when in view (never scroll-coupled); reduced motion shows
 * the finished state. The lines mirror real run_events templates. */

const FEED = [
  { stage: "Queued", text: "Run accepted — 2 credits reserved." },
  { stage: "Ingest", text: "Creative loaded — analysing as image." },
  { stage: "Vision", text: "Layer 1 — OCR, layout geometry and visual measurements." },
  { stage: "Language", text: "Layer 2 — 11 segments, 4 claim candidates; routed to 3 regulatory frameworks." },
  { stage: "Retrieval", text: "Regulation retrieval online — grounding the review for 3 frameworks." },
  { stage: "Review", text: "Review round 1/3 — grounded model review of 4 claim candidates in progress." },
  { stage: "Verify", text: "Round 1 returned 5 findings; handing off to deterministic verification." },
  { stage: "Verify", text: "Deterministic verification passed all 52 checks." },
  { stage: "Done", text: "Report compiled — 5 findings recorded." },
];

const CHECKLIST = [
  { fw: "TILA / Reg Z", status: "flagged", note: "Triggering term without required disclosures" },
  { fw: "FTC", status: "flagged", note: "Unsubstantiated performance claim" },
  { fw: "CFPB / UDAAP", status: "passed", note: "No deceptive-practice signals" },
];

export function LiveReview() {
  const reduced = usePrefersReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const [inView, setInView] = useState(false);
  const [step, setStep] = useState(0);
  const done = step >= FEED.length;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setInView(true);
          io.disconnect();
        }
      },
      { threshold: 0.3 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (!inView || reduced || done) return;
    const t = setTimeout(() => setStep((s) => s + 1), step === 0 ? 400 : 900);
    return () => clearTimeout(t);
  }, [inView, reduced, step, done]);

  const visible = reduced ? FEED.length : step;

  return (
    <section
      id="live"
      aria-label="Watch a review happen live"
      className="relative border-y border-line bg-brushed"
    >
      <div className="container-wide py-20 sm:py-28" ref={ref}>
        <div className="mx-auto max-w-2xl text-center">
          <p className="eyebrow">Live review</p>
          <h2 className="text-chrome mt-3 font-display text-4xl font-bold tracking-[-0.02em] text-balance sm:text-5xl">
            Watch the engine think.
          </h2>
          <p className="mt-4 text-[15.5px] leading-relaxed text-ink-600 text-pretty">
            From the moment you upload, the workspace narrates every stage —
            what was extracted, which frameworks apply, how each review round
            went. Aggregate signals only; your creative and the model&apos;s
            reasoning stay private.
          </p>
        </div>

        <div className="mt-14 grid items-start gap-6 lg:grid-cols-[1.15fr_1fr]">
          {/* the activity feed */}
          <div className="card overflow-hidden">
            <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
              <span className="inline-flex items-center gap-2 text-[13px] font-semibold text-ink-700">
                <Activity className="size-4 text-ink-500" aria-hidden />
                Live activity
              </span>
              <span
                className={cn(
                  "inline-flex items-center gap-1.5 text-[12px] font-semibold",
                  done ? "text-emerald-300" : "text-ink-600"
                )}
              >
                {done ? (
                  <>
                    <CheckCircle2 className="size-3.5" aria-hidden /> Complete
                  </>
                ) : (
                  <>
                    <Loader2 className="size-3.5 animate-spin" aria-hidden />
                    Running
                  </>
                )}
              </span>
            </div>
            <ol className="min-h-[352px] space-y-0.5 p-3">
              {FEED.slice(0, visible).map((f, i) => {
                const active = !reduced && !done && i === visible - 1;
                return (
                  <li
                    key={i}
                    className="flex animate-fade-up items-start gap-3 rounded-xl px-2.5 py-2"
                  >
                    <span className="mt-1 w-[74px] shrink-0 font-mono text-[10.5px] font-bold tracking-wider text-ink-500 uppercase">
                      {f.stage}
                    </span>
                    <span
                      className={cn(
                        "text-[13.5px] leading-relaxed",
                        active ? "text-shimmer" : "text-ink-700"
                      )}
                    >
                      {f.text}
                    </span>
                  </li>
                );
              })}
            </ol>
          </div>

          {/* the checklist outcome */}
          <div className="card overflow-hidden">
            <div className="border-b border-line px-5 py-3.5">
              <span className="text-[13px] font-semibold text-ink-700">
                Framework checklist — the report&apos;s spine
              </span>
            </div>
            <ul className="space-y-2.5 p-4">
              {CHECKLIST.map((c) => (
                <li
                  key={c.fw}
                  className={cn(
                    "rounded-xl border p-3.5 transition-opacity duration-500",
                    done || reduced ? "opacity-100" : "opacity-35",
                    c.status === "flagged"
                      ? "border-red-400/20 bg-red-400/[0.06]"
                      : "border-emerald-400/20 bg-emerald-400/[0.06]"
                  )}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-mono text-[12.5px] font-bold text-ink-850">
                      {c.fw}
                    </span>
                    {c.status === "flagged" ? (
                      <span className="badge-fail">
                        <CircleAlert className="size-3.5" aria-hidden />
                        Potential issue
                      </span>
                    ) : (
                      <span className="badge-pass">
                        <CheckCircle2 className="size-3.5" aria-hidden />
                        Passed
                      </span>
                    )}
                  </div>
                  <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-600">
                    {c.note}
                  </p>
                </li>
              ))}
              <li className="flex items-center gap-2 px-1 pt-1 text-[12.5px] font-medium text-ink-500">
                <ChevronRight className="size-3.5" aria-hidden />
                Each flag opens the exact quoted evidence and suggested fixes.
              </li>
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}

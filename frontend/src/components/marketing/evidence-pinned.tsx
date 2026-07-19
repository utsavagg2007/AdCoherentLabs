"use client";

/** Pinned three-beat story over the signal/evidence clip. The section spans
 * three viewports; the visual stays pinned while Extract -> Ground -> Defend
 * reveal one at a time. Reduced motion: static still + all three blocks. */

import { useEffect, useRef, useState } from "react";
import { FileSearch2, Scale, ShieldCheck } from "lucide-react";
import { usePrefersReducedMotion } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const BEATS = [
  {
    key: "extract",
    icon: FileSearch2,
    title: "Extract",
    body: "Turn creative copy, imagery, claims, disclosures, and entities into reviewable evidence.",
    detail:
      "OCR and computer vision read the creative; NLP structures what it says — every claim, qualifier, and disclosure becomes an addressable piece of evidence.",
  },
  {
    key: "ground",
    icon: Scale,
    title: "Ground",
    body: "Connect the review to applicable regulatory context and cited source material.",
    detail:
      "The review retrieves the regulation text that applies — TILA, Regulation DD, UDAAP, state UDAP — and every finding quotes the ad and cites its source.",
  },
  {
    key: "defend",
    icon: ShieldCheck,
    title: "Defend",
    body: "Verify findings with deterministic checks, provenance, remediation, and a human-review path.",
    detail:
      "A deterministic rule engine audits the AI review itself. What survives ships with remediation, model and ruleset provenance, and an escalation path to your reviewers.",
  },
];

function clamp(v: number, a: number, b: number) {
  return Math.min(b, Math.max(a, v));
}

export function EvidencePinned() {
  const reduced = usePrefersReducedMotion();
  const trackRef = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (reduced) return;
    const track = trackRef.current;
    if (!track) return;
    let raf = 0;
    let last = -1;
    const frame = () => {
      const rect = track.getBoundingClientRect();
      const scrollable = rect.height - window.innerHeight;
      const p = scrollable > 0 ? clamp(-rect.top / scrollable, 0, 0.999) : 0;
      const idx = Math.min(BEATS.length - 1, Math.floor(p * BEATS.length));
      if (idx !== last) {
        last = idx;
        setActive(idx);
      }
    };
    const tick = () => {
      raf = requestAnimationFrame(tick);
      frame();
    };
    const onScroll = () => frame();
    raf = requestAnimationFrame(tick);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
    };
  }, [reduced]);

  const jumpTo = (i: number) => {
    const track = trackRef.current;
    if (!track) return;
    const top = track.offsetTop;
    const scrollable = track.offsetHeight - window.innerHeight;
    window.scrollTo({
      top: top + (scrollable * (i + 0.08)) / BEATS.length,
      behavior: reduced ? "auto" : "smooth",
    });
  };

  return (
    <section
      id="how-it-works"
      ref={trackRef}
      data-surface="dark"
      className={cn("relative bg-ink-950", reduced ? "" : "h-[300vh]")}
      aria-label="How the review works"
    >
      <div
        className={cn(
          "top-0 flex min-h-svh w-full flex-col overflow-hidden",
          reduced ? "relative py-20" : "sticky h-svh"
        )}
      >
        {/* backdrop clip */}
        {reduced ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src="/videos/signal-still.jpg"
            alt=""
            className="absolute inset-0 size-full object-cover opacity-45"
          />
        ) : (
          <video
            className="absolute inset-0 size-full object-cover opacity-55"
            src="/videos/signal-evidence.mp4"
            poster="/videos/signal-poster.jpg"
            autoPlay
            loop
            muted
            playsInline
            preload="metadata"
            tabIndex={-1}
            aria-hidden
          />
        )}
        <div className="absolute inset-0 bg-gradient-to-b from-ink-950 via-ink-950/40 to-ink-950" />
        <div className="absolute inset-0 bg-gradient-to-r from-ink-950/80 via-transparent to-ink-950/40" />

        <div className="container-wide relative flex flex-1 flex-col justify-center py-16">
          <p className="eyebrow text-violet-300/90">The evidence pipeline</p>
          <h2 className="mt-3 max-w-2xl text-4xl font-extrabold tracking-[-0.02em] text-white text-balance sm:text-5xl">
            From creative to defensible review.
          </h2>

          <div className="mt-12 grid gap-10 lg:grid-cols-[420px_1fr] lg:gap-16">
            {/* beat list */}
            <ol className="space-y-2" role="tablist" aria-label="Review stages">
              {BEATS.map((b, i) => {
                const on = reduced || i === active;
                const Icon = b.icon;
                return (
                  <li key={b.key}>
                    <button
                      role="tab"
                      aria-selected={on}
                      onClick={() => (reduced ? setActive(i) : jumpTo(i))}
                      className={cn(
                        "group flex w-full items-start gap-4 rounded-2xl border p-4 text-left transition-all duration-500",
                        on
                          ? "border-violet-400/30 bg-violet-500/10"
                          : "border-white/8 bg-white/[0.02] opacity-50 hover:opacity-80"
                      )}
                    >
                      <span
                        className={cn(
                          "flex size-10 shrink-0 items-center justify-center rounded-xl transition-colors",
                          on
                            ? "bg-violet-500/25 text-violet-200"
                            : "bg-white/8 text-white/50"
                        )}
                      >
                        <Icon className="size-4.5" aria-hidden />
                      </span>
                      <span className="min-w-0">
                        <span className="flex items-baseline gap-2.5">
                          <span className="font-mono text-[11px] font-bold text-violet-300/70">
                            0{i + 1}
                          </span>
                          <span className="text-lg font-extrabold tracking-tight text-white">
                            {b.title}
                          </span>
                        </span>
                        <span className="mt-1 block text-[13.5px] leading-relaxed text-white/60">
                          {b.body}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>

            {/* active detail card */}
            <div className="flex items-center">
              {BEATS.map((b, i) => {
                const on = reduced ? i === active : i === active;
                return (
                  <div
                    key={b.key}
                    role="tabpanel"
                    hidden={!on}
                    className={cn(
                      "glass-dark w-full max-w-xl rounded-3xl p-8 shadow-(--shadow-hud)",
                      on && "animate-fade-up"
                    )}
                  >
                    <p className="font-mono text-[11px] font-bold tracking-[0.2em] text-violet-300/80 uppercase">
                      Stage 0{i + 1} — {b.title}
                    </p>
                    <p className="mt-4 text-xl leading-relaxed font-semibold text-white/90 text-pretty">
                      {b.detail}
                    </p>
                    <div className="mt-6 flex items-center gap-2" aria-hidden>
                      {BEATS.map((_, j) => (
                        <span
                          key={j}
                          className={cn(
                            "h-1 rounded-full transition-all duration-500",
                            j === i ? "w-8 bg-violet-400" : "w-3 bg-white/15"
                          )}
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

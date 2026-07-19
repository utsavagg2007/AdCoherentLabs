"use client";

/** Scroll-scrubbed hero. The clip runs chaos -> assembled dashboard; scroll
 * position maps to video time via requestAnimationFrame with metadata guards
 * and eased seeking. Reduced motion gets the assembled still, no scrub track.
 * Normal document flow throughout — scrolling is never trapped. */

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ChevronDown,
  FileSearch,
  Link2,
  ScanSearch,
  ShieldCheck,
} from "lucide-react";
import { usePrefersReducedMotion } from "@/lib/hooks";
import { cn } from "@/lib/utils";

const HUD_ITEMS = [
  {
    at: 0.22,
    icon: ScanSearch,
    label: "Claim detected",
    sub: "Triggering terms in headline copy",
  },
  {
    at: 0.44,
    icon: FileSearch,
    label: "Disclosure checked",
    sub: "Prominence and proximity evaluated",
  },
  {
    at: 0.66,
    icon: Link2,
    label: "Evidence linked",
    sub: "Quoted copy tied to citations",
  },
  {
    at: 0.86,
    icon: ShieldCheck,
    label: "Review ready",
    sub: "Deterministic checks complete",
  },
];

function clamp(v: number, a: number, b: number) {
  return Math.min(b, Math.max(a, v));
}

export function ScrubHero() {
  const reduced = usePrefersReducedMotion();
  const trackRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const barRef = useRef<HTMLDivElement>(null);
  const [step, setStep] = useState(0); // discrete HUD reveal count
  const [started, setStarted] = useState(false); // fades the scroll cue

  useEffect(() => {
    if (reduced) return;
    const video = videoRef.current;
    const track = trackRef.current;
    const stage = stageRef.current;
    if (!video || !track || !stage) return;

    video.pause(); // scrub source only — never autoplays

    let raf = 0;
    let current = 0;
    let lastStep = -1;
    let lastStarted = false;

    const frame = () => {
      const rect = track.getBoundingClientRect();
      const scrollable = rect.height - window.innerHeight;
      const p = scrollable > 0 ? clamp(-rect.top / scrollable, 0, 1) : 0;

      // continuous effects run through a CSS var — no React re-render
      stage.style.setProperty("--hero-p", p.toFixed(4));
      if (barRef.current)
        barRef.current.style.transform = `scaleX(${p.toFixed(4)})`;

      const nextStep = HUD_ITEMS.filter((h) => p >= h.at).length;
      if (nextStep !== lastStep) {
        lastStep = nextStep;
        setStep(nextStep);
      }
      const nowStarted = p > 0.04;
      if (nowStarted !== lastStarted) {
        lastStarted = nowStarted;
        setStarted(nowStarted);
      }

      // metadata guard: only seek once duration is known and decodable
      const dur = video.duration;
      if (Number.isFinite(dur) && dur > 0 && video.readyState >= 1) {
        const target = p * (dur - 0.06);
        current += (target - current) * 0.18; // eased pursuit for smoothness
        if (Math.abs(target - current) < 0.004) current = target;
        if (!video.seeking && Math.abs(video.currentTime - current) > 0.012) {
          try {
            video.currentTime = current;
          } catch {
            /* not seekable yet */
          }
        }
      }
    };
    const tick = () => {
      raf = requestAnimationFrame(tick);
      frame();
    };
    // rAF drives the eased pursuit; a passive scroll listener keeps the scrub
    // honest even when the browser throttles animation frames.
    const onScroll = () => frame();
    raf = requestAnimationFrame(tick);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
    };
  }, [reduced]);

  const visibleSteps = reduced ? HUD_ITEMS.length : step;

  return (
    <section
      ref={trackRef}
      data-surface="dark"
      className={cn(
        "relative bg-ink-950",
        reduced ? "min-h-svh" : "h-[320vh] sm:h-[340vh]"
      )}
      aria-label="AdCoherent Labs — proof before publish"
    >
      <div
        ref={stageRef}
        className={cn(
          "top-0 h-svh w-full overflow-hidden",
          reduced ? "relative" : "sticky"
        )}
        style={{ ["--hero-p" as string]: 0 }}
      >
        {/* backdrop: scrubbed clip, or the assembled still for reduced motion */}
        {reduced ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src="/videos/hero-still.jpg"
            alt=""
            className="absolute inset-0 size-full object-cover opacity-90 animate-fade-in"
          />
        ) : (
          <video
            ref={videoRef}
            className="absolute inset-0 size-full object-cover"
            src="/videos/hero-assembly.mp4"
            poster="/videos/hero-poster.jpg"
            muted
            playsInline
            preload="auto"
            tabIndex={-1}
            aria-hidden
          />
        )}
        {/* legibility washes */}
        <div className="absolute inset-0 bg-gradient-to-r from-ink-950/85 via-ink-950/30 to-ink-950/20" />
        <div className="absolute inset-0 bg-gradient-to-b from-ink-950/60 via-transparent to-ink-950/70" />

        {/* content */}
        <div className="container-wide relative flex h-full flex-col justify-center pt-16">
          <div className="grid items-center gap-10 lg:grid-cols-[1.1fr_0.9fr]">
            {/* copy */}
            <div
              className="max-w-xl"
              style={
                reduced
                  ? undefined
                  : {
                      transform:
                        "translateY(calc(var(--hero-p) * -26px))",
                    }
              }
            >
              <p className="eyebrow text-violet-300/90 animate-fade-up">
                AI-assisted fintech ad compliance
              </p>
              <h1
                className="mt-4 text-[44px] leading-[1.02] font-extrabold tracking-[-0.03em] text-white text-balance sm:text-6xl lg:text-7xl animate-fade-up"
                style={{ animationDelay: "80ms" }}
              >
                Proof before publish.
              </h1>
              <p
                className="mt-5 max-w-md text-[17px] leading-relaxed text-white/70 text-pretty animate-fade-up"
                style={{ animationDelay: "160ms" }}
              >
                Upload a creative. Surface claims, disclosures, and
                regulation-grounded findings your compliance team can review.
              </p>
              <div
                className="mt-8 flex flex-wrap items-center gap-3 animate-fade-up"
                style={{ animationDelay: "240ms" }}
              >
                <Link href="/signup" className="btn-primary !h-12 !px-6 text-[15px]">
                  Run a compliance check
                  <ArrowRight className="size-4" aria-hidden />
                </Link>
                <a href="#how-it-works" className="btn-ghost-dark !h-12 !px-6 text-[15px]">
                  See how it works
                </a>
              </div>
              <p
                className="mt-5 text-[13px] font-medium text-white/45 animate-fade-up"
                style={{ animationDelay: "320ms" }}
              >
                Decision support, not legal advice.
              </p>
            </div>

            {/* illustrative HUD */}
            <div className="hidden justify-end lg:flex">
              <div className="glass-dark w-[340px] rounded-2xl p-5 shadow-(--shadow-hud)">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-[12px] font-bold tracking-wide text-white/85">
                    Assembling review
                  </p>
                  <span className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] font-semibold tracking-wider text-white/40 uppercase">
                    Illustrative interface
                  </span>
                </div>
                <div className="mt-3 h-1 overflow-hidden rounded-full bg-white/10">
                  <div
                    ref={barRef}
                    className="h-full origin-left rounded-full bg-violet-500"
                    style={{
                      transform: reduced ? "scaleX(1)" : "scaleX(0)",
                    }}
                  />
                </div>
                <ul className="mt-4 space-y-2.5" aria-live="off">
                  {HUD_ITEMS.map((item, i) => {
                    const on = i < visibleSteps;
                    const Icon = item.icon;
                    return (
                      <li
                        key={item.label}
                        className={cn(
                          "flex items-start gap-3 rounded-xl border p-3 transition-all duration-500",
                          on
                            ? "translate-y-0 border-violet-400/25 bg-violet-500/10 opacity-100"
                            : "translate-y-1.5 border-white/8 bg-white/[0.03] opacity-40"
                        )}
                      >
                        <span
                          className={cn(
                            "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg",
                            on
                              ? "bg-violet-500/25 text-violet-200"
                              : "bg-white/8 text-white/40"
                          )}
                        >
                          <Icon className="size-3.5" aria-hidden />
                        </span>
                        <span className="min-w-0">
                          <span className="block text-[13px] leading-tight font-bold text-white/90">
                            {item.label}
                          </span>
                          <span className="mt-0.5 block text-[11.5px] leading-snug text-white/45">
                            {item.sub}
                          </span>
                        </span>
                        <span
                          aria-hidden
                          className={cn(
                            "ml-auto mt-1 size-1.5 shrink-0 rounded-full",
                            on ? "bg-violet-400" : "bg-white/15"
                          )}
                        />
                      </li>
                    );
                  })}
                </ul>
              </div>
            </div>
          </div>
        </div>

        {/* scroll cue */}
        {!reduced && (
          <div
            className={cn(
              "absolute bottom-7 left-1/2 -translate-x-1/2 text-white/50 transition-opacity duration-500",
              started ? "opacity-0" : "opacity-100"
            )}
            aria-hidden
          >
            <div className="flex flex-col items-center gap-1.5">
              <span className="text-[11px] font-bold tracking-[0.2em] uppercase">
                Scroll
              </span>
              <ChevronDown className="size-4 animate-bounce" />
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

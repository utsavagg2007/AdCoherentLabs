"use client";

/** Factual product metrics only — counters animate on first view. */

import { useEffect, useRef, useState } from "react";
import { usePrefersReducedMotion } from "@/lib/hooks";

const METRICS = [
  {
    value: 4,
    suffix: "",
    label: "Analysis layers",
    detail:
      "OCR/CV extraction, NLP claim and disclosure detection, regulation-grounded AI review, deterministic verification.",
  },
  {
    value: 50,
    suffix: "+",
    label: "Deterministic checks",
    detail:
      "Rule-engine checks audit every AI review for soundness, coverage, and asset-level defects before it reaches you.",
  },
  {
    value: 6,
    suffix: "",
    label: "Creative formats",
    detail:
      "Images, carousels, video, PDF, Word documents, and raw copy all flow through the same four-layer review.",
  },
];

function Counter({
  value,
  suffix,
  animate,
}: {
  value: number;
  suffix: string;
  animate: boolean;
}) {
  // rAF drives the count-up; without animation the final value renders directly
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (!animate) return;
    let raf = 0;
    const t0 = performance.now();
    const dur = 1400;
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / dur);
      setProgress(1 - Math.pow(1 - p, 4));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [animate]);

  const display = animate ? Math.round(value * progress) : value;

  return (
    <span className="text-chrome font-display text-6xl font-bold tracking-[-0.04em] tabular-nums sm:text-7xl">
      {display}
      {suffix}
    </span>
  );
}

export function Metrics() {
  const reduced = usePrefersReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setInView(true);
          obs.disconnect();
        }
      },
      { threshold: 0.35 }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  return (
    <section aria-label="Product facts" className="bg-spotlight">
      <div ref={ref} className="container-page py-20 sm:py-28">
        <div className="grid gap-12 sm:grid-cols-3 sm:gap-8">
          {METRICS.map((m) => (
            <div key={m.label} className="text-center sm:text-left">
              <Counter
                value={m.value}
                suffix={m.suffix}
                animate={inView && !reduced}
              />
              <p className="mt-3 text-[15px] font-bold text-ink-850">
                {m.label}
              </p>
              <p className="mx-auto mt-2 max-w-xs text-[13.5px] leading-relaxed text-ink-500 sm:mx-0">
                {m.detail}
              </p>
            </div>
          ))}
        </div>
        <p className="mt-12 text-center text-[12px] text-ink-500">
          Facts describe the analysis pipeline, not legal coverage. Findings
          always ship with their evidence.
        </p>
      </div>
    </section>
  );
}

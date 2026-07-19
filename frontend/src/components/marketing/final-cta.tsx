"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { usePrefersReducedMotion } from "@/lib/hooks";

/** Final CTA over the calm-review clip — bright, quiet, confident. */

export function FinalCta() {
  const reduced = usePrefersReducedMotion();

  return (
    <section aria-label="Start a review" className="relative overflow-hidden">
      {reduced ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src="/videos/calm-still.jpg"
          alt=""
          className="absolute inset-0 size-full object-cover"
        />
      ) : (
        <video
          className="absolute inset-0 size-full object-cover"
          src="/videos/calm-review.mp4"
          poster="/videos/calm-poster.jpg"
          autoPlay
          loop
          muted
          playsInline
          preload="metadata"
          tabIndex={-1}
          aria-hidden
        />
      )}
      {/* wash for legibility over the bright scene */}
      <div className="absolute inset-0 bg-gradient-to-b from-paper via-paper/40 to-paper/85" />

      <div className="container-page relative flex min-h-[80vh] items-center justify-center py-24">
        <div className="glass-light max-w-xl rounded-3xl p-9 text-center shadow-(--shadow-float) sm:p-12">
          <h2 className="text-4xl font-extrabold tracking-[-0.03em] text-ink-900 text-balance sm:text-5xl">
            Go to market with a review trail.
          </h2>
          <p className="mx-auto mt-4 max-w-md text-[16px] leading-relaxed text-zinc-600 text-pretty">
            Give every launch a clearer path from creative to compliance
            review.
          </p>
          <div className="mt-8 flex justify-center">
            <Link href="/signup" className="btn-primary !h-12 !px-7 text-[15px]">
              Start a review
              <ArrowRight className="size-4" aria-hidden />
            </Link>
          </div>
          <p className="mt-5 text-[12px] font-medium text-zinc-400">
            Free plan · 25 credits monthly · no card required
          </p>
        </div>
      </div>
    </section>
  );
}

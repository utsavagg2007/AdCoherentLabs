"use client";

import Link from "next/link";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, ShieldCheck, Scale, FileSearch } from "lucide-react";

/** The hero: one calm 5s ambient chrome loop (autoplay, muted, looped) with
 * the headline over its negative space. No scroll-scrubbing, no scroll
 * listeners — scrolling never drives media. Reduced-motion users (and any
 * browser that declines autoplay) simply keep the still. */
export function Hero() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [motionOk, setMotionOk] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setMotionOk(!mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (motionOk) videoRef.current?.play().catch(() => {});
  }, [motionOk]);

  return (
    <section className="relative isolate flex min-h-[100svh] items-end overflow-hidden bg-coal-950 bg-noise">
      {/* media backdrop */}
      <div className="absolute inset-0" aria-hidden>
        <Image
          src="/media/hero-still.jpg"
          alt=""
          fill
          priority
          sizes="100vw"
          className="object-cover"
          placeholder="blur"
          blurDataURL="/media/hero-blur.jpg"
        />
        {motionOk && (
          <video
            ref={videoRef}
            className="absolute inset-0 size-full object-cover"
            src="/media/hero-loop.mp4"
            poster="/media/hero-still.jpg"
            muted
            loop
            playsInline
            preload="metadata"
            autoPlay
          />
        )}
        {/* legibility + edge fades */}
        <div className="absolute inset-0 bg-gradient-to-r from-coal-950/85 via-coal-950/35 to-transparent" />
        <div className="absolute inset-x-0 bottom-0 h-40 bg-gradient-to-t from-coal-950 to-transparent" />
        <div className="absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-coal-950/70 to-transparent" />
      </div>

      <div className="container-wide relative pt-32 pb-16 sm:pb-20">
        <div className="max-w-2xl">
          <p className="eyebrow animate-fade-in text-ink-600">
            Fintech ad compliance · four AI layers · deterministic verification
          </p>
          <h1 className="text-chrome mt-5 animate-fade-up text-[clamp(2.6rem,6.5vw,4.6rem)] leading-[1.02] font-bold text-balance">
            Every claim in your ad, verified before it ships.
          </h1>
          <p
            className="mt-6 max-w-xl animate-fade-up text-lg leading-relaxed text-ink-700 text-pretty"
            style={{ animationDelay: "120ms" }}
          >
            Upload a creative — image, video, PDF, document or copy. Vision and
            language layers extract every claim, a regulation-grounded model
            reviews it, and a deterministic rule engine verifies the review.
            You watch it happen live.
          </p>
          <div
            className="mt-9 flex animate-fade-up flex-wrap items-center gap-3.5"
            style={{ animationDelay: "220ms" }}
          >
            <Link href="/signup" className="btn-primary sheen px-6 py-3 text-[15px]">
              Run a compliance check
              <ArrowRight className="size-4" />
            </Link>
            <a href="#how-it-works" className="btn-ghost-dark px-6 py-3 text-[15px]">
              See how it works
            </a>
          </div>

          <ul
            className="mt-12 flex animate-fade-up flex-wrap gap-x-7 gap-y-3 text-[13.5px] font-medium text-ink-600"
            style={{ animationDelay: "320ms" }}
          >
            <li className="flex items-center gap-2">
              <FileSearch className="size-4 text-ink-500" aria-hidden />
              Findings quote your ad, verbatim
            </li>
            <li className="flex items-center gap-2">
              <Scale className="size-4 text-ink-500" aria-hidden />
              Grounded in the actual regulation text
            </li>
            <li className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-ink-500" aria-hidden />
              Decision support, not legal advice
            </li>
          </ul>
        </div>
      </div>
    </section>
  );
}

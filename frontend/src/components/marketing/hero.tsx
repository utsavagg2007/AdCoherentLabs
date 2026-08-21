import Link from "next/link";
import Image from "next/image";
import { ArrowRight, FileSearch, Scale, ShieldCheck } from "lucide-react";

/** The hero.
 *
 * Two renders of the brand mark, one lit for each theme, cross-faded by a
 * CSS variant rather than by JavaScript — so the correct one is already on
 * screen at first paint instead of arriving a frame after hydration.
 *
 * The old build ran a 5s video loop here. It went for two reasons: the loop
 * was the previous chrome identity, and a full-bleed h.264 behind the
 * headline was the largest single contributor to how soft the type looked
 * over it. A still render carries the same idea and stays sharp. */
export function Hero() {
  return (
    <section className="bg-wash relative isolate flex min-h-[100svh] items-center overflow-hidden">
      {/* media backdrop — art is composed with its subject on the right, so
          the headline column below lands in real negative space */}
      <div className="absolute inset-0" aria-hidden>
        <Image
          src="/media/hero-light.png"
          alt=""
          fill
          priority
          sizes="100vw"
          className="art-light object-cover object-right"
        />
        <Image
          src="/media/hero-dark.png"
          alt=""
          fill
          priority
          sizes="100vw"
          className="art-dark object-cover object-right"
        />
        {/* legibility ramp: the copy column must clear 4.5:1 over whatever
            the render happens to put behind it, in both themes */}
        <div className="absolute inset-0 bg-[linear-gradient(90deg,var(--surface-canvas)_0%,color-mix(in_oklab,var(--surface-canvas)_82%,transparent)_38%,transparent_72%)]" />
        <div className="absolute inset-x-0 bottom-0 h-40 bg-[linear-gradient(to_top,var(--surface-canvas),transparent)]" />
      </div>

      <div className="container-wide relative pt-32 pb-20">
        <div className="max-w-2xl">
          <p className="eyebrow animate-fade-in flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-brand-text">Fintech ad compliance</span>
            <span className="text-faint" aria-hidden>
              ·
            </span>
            <span>four AI layers</span>
            <span className="text-faint" aria-hidden>
              ·
            </span>
            <span>deterministic verification</span>
          </p>

          <h1 className="text-gradient mt-5 animate-fade-up text-[clamp(2.6rem,6.5vw,4.6rem)] leading-[1.02] font-extrabold text-balance">
            Every claim in your ad, verified before it ships.
          </h1>

          <p
            className="mt-6 max-w-xl animate-fade-up text-lg leading-relaxed text-muted text-pretty"
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
              <ArrowRight className="size-4" aria-hidden />
            </Link>
            <a href="#how-it-works" className="btn-secondary px-6 py-3 text-[15px]">
              See how it works
            </a>
          </div>

          <ul
            className="mt-12 flex animate-fade-up flex-wrap gap-x-7 gap-y-3 text-[13.5px] font-medium text-muted"
            style={{ animationDelay: "320ms" }}
          >
            <li className="flex items-center gap-2">
              <FileSearch className="size-4 text-brand-text" aria-hidden />
              Findings quote your ad, verbatim
            </li>
            <li className="flex items-center gap-2">
              <Scale className="size-4 text-accent-text" aria-hidden />
              Grounded in the actual regulation text
            </li>
            <li className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-pass" aria-hidden />
              Decision support, not legal advice
            </li>
          </ul>
        </div>
      </div>
    </section>
  );
}

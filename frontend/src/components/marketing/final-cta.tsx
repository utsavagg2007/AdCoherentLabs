import Link from "next/link";
import Image from "next/image";
import { ArrowRight } from "lucide-react";
import { Reveal } from "./reveal";

/** Final CTA — the brand render, one glass panel, one action.
 * Static imagery by design: the page's only motion budget is the hero. */

export function FinalCta() {
  return (
    <section aria-label="Start a review" className="relative overflow-hidden">
      <Image
        src="/media/hero-light.png"
        alt=""
        fill
        sizes="100vw"
        className="art-light object-cover object-left"
        aria-hidden
      />
      <Image
        src="/media/hero-dark.png"
        alt=""
        fill
        sizes="100vw"
        className="art-dark object-cover object-left"
        aria-hidden
      />
      <div className="absolute inset-0 bg-[linear-gradient(to_bottom,var(--surface-canvas),color-mix(in_oklab,var(--surface-canvas)_60%,transparent)_45%,var(--surface-canvas))]" />

      <div className="container-page relative flex min-h-[72vh] items-center justify-center py-24">
        <Reveal className="w-full max-w-xl">
          <div className="glass rounded-3xl p-9 text-center shadow-(--shadow-float) sm:p-12">
            <h2 className="text-gradient font-display text-4xl font-bold tracking-[-0.03em] text-balance sm:text-5xl">
              Go to market with a review trail.
            </h2>
            <p className="mx-auto mt-4 max-w-md text-[16px] leading-relaxed text-muted text-pretty">
              Give every launch a clearer path from creative to compliance
              review.
            </p>
            <div className="mt-8 flex justify-center">
              <Link
                href="/signup"
                className="btn-primary sheen !h-12 !px-7 text-[15px]"
              >
                Start a review
                <ArrowRight className="size-4" aria-hidden />
              </Link>
            </div>
            <p className="mt-5 text-[12px] font-medium text-subtle">
              Free plan · 25 credits monthly · no card required
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

import Link from "next/link";
import Image from "next/image";
import { ArrowRight } from "lucide-react";
import { Reveal } from "./reveal";

/** Final CTA — the chrome monolith still, one glass panel, one action.
 * Static imagery by design: the page's only motion budget is the hero. */

export function FinalCta() {
  return (
    <section aria-label="Start a review" className="relative overflow-hidden">
      <Image
        src="/media/hero-still.jpg"
        alt=""
        fill
        sizes="100vw"
        className="object-cover object-right"
        aria-hidden
      />
      <div className="absolute inset-0 bg-gradient-to-b from-coal-900 via-coal-950/55 to-coal-950" />

      <div className="container-page relative flex min-h-[72vh] items-center justify-center py-24">
        <Reveal className="w-full max-w-xl">
          <div className="glass-dark rounded-3xl p-9 text-center shadow-(--shadow-float) sm:p-12">
            <h2 className="text-chrome font-display text-4xl font-bold tracking-[-0.03em] text-balance sm:text-5xl">
              Go to market with a review trail.
            </h2>
            <p className="mx-auto mt-4 max-w-md text-[16px] leading-relaxed text-ink-700 text-pretty">
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
            <p className="mt-5 text-[12px] font-medium text-ink-500">
              Free plan · 25 credits monthly · no card required
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

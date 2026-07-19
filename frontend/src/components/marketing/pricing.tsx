import Link from "next/link";
import { Check } from "lucide-react";
import { PLANS } from "@/lib/plans";
import { cn } from "@/lib/utils";

/** Five real tiers. No invented dollar prices, no annual toggle — checkout is
 * Stripe-hosted and monthly; Enterprise is provisioned manually. */

export function Pricing() {
  return (
    <section id="pricing" aria-label="Pricing" className="bg-paper">
      <div className="container-wide py-20 sm:py-28">
        <div className="mx-auto max-w-2xl text-center">
          <p className="eyebrow text-violet-600">Pricing</p>
          <h2 className="mt-3 text-4xl font-extrabold tracking-[-0.02em] text-ink-900 text-balance sm:text-5xl">
            Credits are the only meter.
          </h2>
          <p className="mt-4 text-[16px] leading-relaxed text-zinc-500 text-pretty">
            Every plan runs the same four-layer review. Plans set your monthly
            credit allowance, upload cap, seats, and API access — final prices
            are shown at checkout.
          </p>
        </div>

        <div className="mt-14 grid gap-4 md:grid-cols-2 lg:grid-cols-5 lg:gap-3">
          {PLANS.map((plan) => {
            const featured = plan.tier === "pro";
            return (
              <div
                key={plan.tier}
                className={cn(
                  "relative flex flex-col rounded-2xl border bg-white p-5",
                  featured
                    ? "border-violet-300 shadow-[0_0_0_3px_rgb(139_92_246/0.15),var(--shadow-float)] lg:-my-3 lg:py-8"
                    : "border-line shadow-(--shadow-soft)"
                )}
              >
                {featured && (
                  <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-violet-600 px-3 py-1 text-[10.5px] font-bold tracking-wider text-white uppercase">
                    Most popular
                  </span>
                )}
                <h3 className="text-[15px] font-extrabold text-ink-900">
                  {plan.name}
                </h3>
                <p className="mt-1 min-h-9 text-[12px] leading-snug text-zinc-500">
                  {plan.tagline}
                </p>
                <div className="mt-4">
                  {plan.monthlyCredits !== null ? (
                    <>
                      <span className="text-[34px] leading-none font-extrabold tracking-tight text-ink-900 tabular-nums">
                        {plan.monthlyCredits.toLocaleString()}
                      </span>
                      <span className="ml-1.5 text-[12px] font-semibold text-zinc-400">
                        credits / month
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="text-[34px] leading-none font-extrabold tracking-tight text-ink-900">
                        Custom
                      </span>
                      <span className="ml-1.5 text-[12px] font-semibold text-zinc-400">
                        provisioned credits
                      </span>
                    </>
                  )}
                </div>
                <ul className="mt-5 flex-1 space-y-2">
                  {plan.highlights.map((h) => (
                    <li
                      key={h}
                      className="flex items-start gap-2 text-[12.5px] leading-snug text-zinc-600"
                    >
                      <Check
                        className="mt-0.5 size-3.5 shrink-0 text-violet-600"
                        aria-hidden
                      />
                      {h}
                    </li>
                  ))}
                </ul>
                <div className="mt-6">
                  {plan.tier === "enterprise" ? (
                    <a
                      href="mailto:sales@adcoherentlabs.com?subject=Enterprise%20plan"
                      className="btn-secondary w-full !text-[13px]"
                    >
                      Talk to sales
                    </a>
                  ) : plan.tier === "free" ? (
                    <Link href="/signup" className="btn-secondary w-full !text-[13px]">
                      Start free
                    </Link>
                  ) : (
                    <Link
                      href={`/signup?plan=${plan.tier}`}
                      className={cn(
                        "w-full !text-[13px]",
                        featured ? "btn-primary" : "btn-secondary"
                      )}
                    >
                      Choose plan
                    </Link>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="mx-auto mt-10 max-w-2xl text-center text-[12.5px] leading-relaxed text-zinc-400">
          <p>
            Seats: 1 · 2 · 8 · 20 · custom. A text review costs 1–10 credits
            depending on plan; images and HTML cost more, carousels price per
            card. The in-app price list is exactly what is enforced.
          </p>
          <p className="mt-2">
            Paid plans check out monthly through Stripe. Upgrades, credit
            packs, and billing management live in the app.
          </p>
        </div>
      </div>
    </section>
  );
}

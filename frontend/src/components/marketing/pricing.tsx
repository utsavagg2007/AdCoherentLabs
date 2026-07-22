import Link from "next/link";
import { Check, Sparkles } from "lucide-react";
import { Reveal } from "./reveal";
import { cn } from "@/lib/utils";

/** Pricing — rendered EXCLUSIVELY from the backend's GET /v1/plans
 * (plan_pricing + plan_entitlements + credit_costs). Server component:
 * fetched with ISR, so a price change in the database is live within two
 * minutes with zero frontend edits. */

interface ApiPlan {
  tier: string;
  name: string;
  tagline: string;
  monthly_usd_cents: number | null;
  credits_per_month: number | null;
  max_upload_mb: number;
  seats: number | null;
  api_access: boolean;
  credit_packs_allowed: boolean;
  allowed_kinds: string[];
  max_video_seconds: number | null;
  max_concurrent_runs: number;
  submissions_per_day: number | null;
}

interface PlansPayload {
  plans: ApiPlan[];
  packs: { pack: string; credits: number; usd_cents: number }[];
}

async function fetchPlans(): Promise<PlansPayload | null> {
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";
  try {
    const res = await fetch(`${base}/v1/plans`, { next: { revalidate: 120 } });
    if (!res.ok) return null;
    return (await res.json()) as PlansPayload;
  } catch {
    return null;
  }
}

function price(cents: number | null): string {
  if (cents === null) return "Custom";
  if (cents === 0) return "$0";
  return `$${(cents / 100).toLocaleString("en-US", {
    maximumFractionDigits: cents % 100 === 0 ? 0 : 2,
  })}`;
}

function mediaLine(p: ApiPlan): string {
  const hasVideo = p.allowed_kinds.includes("video");
  if (!hasVideo) return "Text · images · PDF · documents";
  if (p.max_video_seconds != null)
    return `All formats · video up to ${p.max_video_seconds}s`;
  return "All formats · full-length video";
}

function highlights(p: ApiPlan): string[] {
  const h: string[] = [];
  h.push(
    p.credits_per_month != null
      ? `${p.credits_per_month.toLocaleString()} credits every month`
      : "Contract-provisioned credits"
  );
  h.push(mediaLine(p));
  if (p.api_access) h.push("API access with scoped keys");
  if (p.credit_packs_allowed) h.push("Credit packs when you need more");
  h.push(
    `${p.max_upload_mb} MB uploads · ${
      p.seats != null ? `${p.seats} seat${p.seats === 1 ? "" : "s"}` : "custom seats"
    }`
  );
  if (p.max_concurrent_runs > 1) h.push(`${p.max_concurrent_runs} concurrent runs`);
  return h;
}

export async function Pricing() {
  const data = await fetchPlans();

  return (
    <section id="pricing" aria-label="Pricing" className="bg-spotlight">
      <div className="container-wide py-20 sm:py-28">
        <Reveal className="mx-auto max-w-2xl text-center">
          <p className="eyebrow">Pricing</p>
          <h2 className="text-chrome mt-3 font-display text-4xl font-bold tracking-[-0.02em] text-balance sm:text-5xl">
            Priced by the review, not the seat.
          </h2>
          <p className="mt-4 text-[15.5px] leading-relaxed text-ink-600 text-pretty">
            Every plan runs the same four-layer engine. Credits meter the
            work — the base price of a run plus its actual model usage.
          </p>
        </Reveal>

        {!data ? (
          <div className="card mx-auto mt-14 max-w-md p-8 text-center">
            <p className="text-[15px] font-semibold text-ink-850">
              Live pricing is momentarily unavailable.
            </p>
            <p className="mt-2 text-[13.5px] leading-relaxed text-ink-600">
              Prices are published by the platform in real time. Refresh in a
              moment, or create a free account — the Free plan needs no card.
            </p>
            <Link href="/signup" className="btn-primary mt-6">
              Start free
            </Link>
          </div>
        ) : (
          <>
            <div className="mt-14 grid gap-4 sm:grid-cols-2 lg:grid-cols-5 lg:gap-3">
              {data.plans.map((p, i) => {
                const featured = p.tier === "pro";
                return (
                  <Reveal
                    key={p.tier}
                    delay={i * 60}
                    className={cn("flex", featured && "lg:-my-2")}
                  >
                    <div
                      className={cn(
                        "card relative flex w-full flex-col p-6",
                        featured &&
                          "border-white/25 shadow-(--shadow-float) ring-1 ring-white/10"
                      )}
                    >
                      {featured && (
                        <span className="absolute -top-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1 rounded-full border border-white/20 bg-coal-700 px-3 py-1 text-[11px] font-bold tracking-wider text-ink-850 uppercase shadow-(--shadow-soft)">
                          <Sparkles className="size-3" aria-hidden />
                          Most chosen
                        </span>
                      )}
                      <h3 className="font-display text-lg font-bold text-ink-900">
                        {p.name}
                      </h3>
                      <p className="mt-1 min-h-9 text-[12.5px] leading-snug text-ink-600">
                        {p.tagline}
                      </p>
                      <p className="mt-4">
                        <span className="text-chrome font-display text-4xl font-bold tracking-tight">
                          {price(p.monthly_usd_cents)}
                        </span>
                        {p.monthly_usd_cents !== null && (
                          <span className="ml-1 text-[13px] font-medium text-ink-500">
                            /month
                          </span>
                        )}
                      </p>
                      <ul className="mt-5 flex-1 space-y-2.5">
                        {highlights(p).map((h) => (
                          <li
                            key={h}
                            className="flex items-start gap-2 text-[13px] leading-snug text-ink-700"
                          >
                            <Check
                              className="mt-0.5 size-3.5 shrink-0 text-emerald-300"
                              aria-hidden
                            />
                            {h}
                          </li>
                        ))}
                      </ul>
                      <Link
                        href={
                          p.tier === "enterprise"
                            ? "mailto:sales@adcoherentlabs.com"
                            : `/signup?plan=${p.tier}`
                        }
                        className={cn(
                          "mt-6 w-full",
                          featured ? "btn-primary sheen" : "btn-secondary"
                        )}
                      >
                        {p.tier === "free"
                          ? "Start free"
                          : p.tier === "enterprise"
                            ? "Talk to sales"
                            : `Choose ${p.name}`}
                      </Link>
                    </div>
                  </Reveal>
                );
              })}
            </div>

            {data.packs.length > 0 && (
              <Reveal className="mx-auto mt-10 max-w-2xl">
                <div className="card flex flex-col items-center gap-3 p-5 text-center sm:flex-row sm:justify-between sm:text-left">
                  <p className="text-[13.5px] leading-relaxed text-ink-600">
                    <span className="font-semibold text-ink-850">
                      Credit packs
                    </span>{" "}
                    for burst volume — on any active paid plan, they never
                    expire.
                  </p>
                  <div className="flex shrink-0 flex-wrap justify-center gap-2">
                    {data.packs.map((pk) => (
                      <span key={pk.pack} className="badge-neutral">
                        {pk.credits.toLocaleString()} cr · {price(pk.usd_cents)}
                      </span>
                    ))}
                  </div>
                </div>
              </Reveal>
            )}
          </>
        )}

        <p className="mt-10 text-center text-[12px] text-ink-500">
          Prices are published live by the platform. A run&apos;s final cost =
          its base price + metered model usage, both shown on the report.
        </p>
      </div>
    </section>
  );
}

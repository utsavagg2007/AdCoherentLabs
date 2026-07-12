import type { Tier } from "@/lib/types";

/**
 * Minimal Stripe REST helpers (no SDK dependency). Server only.
 * Playbook Phase 6: Checkout for upgrades, Billing Portal for self-serve
 * changes, and the webhook as the single source of truth for tier state.
 */

export const stripeConfigured = () => Boolean(process.env.STRIPE_SECRET_KEY);

export function priceForTier(tier: string): string | null {
  const map: Record<string, string | undefined> = {
    hobby: process.env.STRIPE_PRICE_HOBBY,
    pro: process.env.STRIPE_PRICE_PRO,
    design: process.env.STRIPE_PRICE_DESIGN,
    enterprise: process.env.STRIPE_PRICE_ENTERPRISE,
  };
  return map[tier] ?? null;
}

export function tierForPrice(priceId: string): Tier | null {
  if (priceId === process.env.STRIPE_PRICE_HOBBY) return "hobby";
  if (priceId === process.env.STRIPE_PRICE_PRO) return "pro";
  if (priceId === process.env.STRIPE_PRICE_DESIGN) return "design";
  if (priceId === process.env.STRIPE_PRICE_ENTERPRISE) return "enterprise";
  return null;
}

export async function stripePost(
  path: string,
  params: Record<string, string>,
): Promise<Record<string, unknown>> {
  const res = await fetch(`https://api.stripe.com/v1/${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.STRIPE_SECRET_KEY}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams(params).toString(),
  });
  const json = (await res.json()) as Record<string, unknown>;
  if (!res.ok) {
    const err = json.error as { message?: string } | undefined;
    throw new Error(err?.message ?? `Stripe error (${res.status})`);
  }
  return json;
}

/** Map Stripe subscription status onto the subscriptions.status constraint. */
export function mapStripeStatus(
  status: string,
): "trialing" | "active" | "past_due" | "canceled" | "incomplete" | "unpaid" {
  switch (status) {
    case "trialing":
    case "active":
    case "past_due":
    case "canceled":
    case "incomplete":
    case "unpaid":
      return status;
    case "incomplete_expired":
    case "paused":
    default:
      return "canceled";
  }
}

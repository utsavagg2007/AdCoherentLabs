import { NextResponse } from "next/server";
import { getSessionState } from "@/lib/data";
import { isDemoMode, siteUrl } from "@/lib/env";
import { stripeConfigured, stripePost } from "@/lib/stripe";

/** Opens the Stripe Billing Portal for self-serve plan changes/cancellation. */
export async function GET() {
  if (isDemoMode) {
    return NextResponse.redirect(new URL("/billing?notice=demo", siteUrl));
  }

  const state = await getSessionState();
  if (state.kind !== "ready") {
    return NextResponse.redirect(new URL("/login", siteUrl));
  }
  const { ctx } = state;
  const customer = ctx.subscription.stripe_customer_id;

  if (!stripeConfigured() || !customer || !["owner", "admin"].includes(ctx.role)) {
    return NextResponse.redirect(
      new URL("/billing?notice=stripe-unconfigured", siteUrl),
    );
  }

  try {
    const session = await stripePost("billing_portal/sessions", {
      customer,
      return_url: `${siteUrl}/billing`,
    });
    return NextResponse.redirect(session.url as string);
  } catch (e) {
    const message = e instanceof Error ? e.message : "portal failed";
    return NextResponse.redirect(
      new URL(`/billing?notice=${encodeURIComponent(message)}`, siteUrl),
    );
  }
}

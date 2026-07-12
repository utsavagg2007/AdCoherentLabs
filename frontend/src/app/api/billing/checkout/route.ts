import { NextResponse } from "next/server";
import { getSessionState } from "@/lib/data";
import { isDemoMode, siteUrl } from "@/lib/env";
import { priceForTier, stripeConfigured, stripePost } from "@/lib/stripe";

/** Creates a Stripe Checkout session for a tier upgrade and redirects to it. */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const tier = url.searchParams.get("tier") ?? "";

  if (isDemoMode) {
    return NextResponse.redirect(new URL("/billing?notice=demo", siteUrl));
  }

  const state = await getSessionState();
  if (state.kind !== "ready") {
    return NextResponse.redirect(new URL("/login", siteUrl));
  }
  const { ctx } = state;
  if (!["owner", "admin"].includes(ctx.role)) {
    return NextResponse.redirect(new URL("/billing", siteUrl));
  }

  const price = priceForTier(tier);
  if (!stripeConfigured() || !price) {
    return NextResponse.redirect(
      new URL("/billing?notice=stripe-unconfigured", siteUrl),
    );
  }

  try {
    const session = await stripePost("checkout/sessions", {
      mode: "subscription",
      "line_items[0][price]": price,
      "line_items[0][quantity]": "1",
      client_reference_id: ctx.org.id,
      customer_email: ctx.user.email,
      // org_id on the subscription is what the webhook uses to sync state.
      "subscription_data[metadata][org_id]": ctx.org.id,
      "metadata[org_id]": ctx.org.id,
      success_url: `${siteUrl}/billing?success=1`,
      cancel_url: `${siteUrl}/billing?canceled=1`,
    });
    return NextResponse.redirect(session.url as string);
  } catch (e) {
    const message = e instanceof Error ? e.message : "checkout failed";
    return NextResponse.redirect(
      new URL(`/billing?notice=${encodeURIComponent(message)}`, siteUrl),
    );
  }
}

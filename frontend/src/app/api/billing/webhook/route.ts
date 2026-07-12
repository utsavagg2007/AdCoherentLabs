import { createHmac, timingSafeEqual } from "crypto";
import { NextResponse } from "next/server";
import { createAdminClient } from "@/lib/supabase/admin";
import { mapStripeStatus, tierForPrice } from "@/lib/stripe";

/**
 * Stripe webhook — THE source of truth for subscription state (playbook
 * Phase 6). Verifies the signature, then upserts `subscriptions` with the
 * service role (explicit org_id — service role bypasses RLS).
 *
 * Subscribe this endpoint to: customer.subscription.created / updated /
 * deleted (checkout.session.completed also carries the subscription, but the
 * subscription events are sufficient because org_id rides on subscription
 * metadata).
 */
export async function POST(request: Request) {
  const secret = process.env.STRIPE_WEBHOOK_SECRET;
  if (!secret) {
    return NextResponse.json({ error: "webhook not configured" }, { status: 501 });
  }

  const payload = await request.text();
  const signature = request.headers.get("stripe-signature") ?? "";
  if (!verifySignature(payload, signature, secret)) {
    return NextResponse.json({ error: "invalid signature" }, { status: 400 });
  }

  const event = JSON.parse(payload) as {
    type: string;
    data: { object: Record<string, unknown> };
  };

  if (!event.type.startsWith("customer.subscription.")) {
    return NextResponse.json({ received: true });
  }

  const sub = event.data.object as {
    id: string;
    customer: string;
    status: string;
    metadata?: { org_id?: string };
    items?: { data?: { price?: { id?: string } }[] };
    current_period_start?: number;
    current_period_end?: number;
  };

  const orgId = sub.metadata?.org_id;
  if (!orgId) {
    // Without org metadata we cannot attribute the subscription to a tenant.
    return NextResponse.json({ received: true, warning: "no org_id metadata" });
  }

  const priceId = sub.items?.data?.[0]?.price?.id ?? "";
  const tier =
    event.type === "customer.subscription.deleted"
      ? "free"
      : (tierForPrice(priceId) ?? "free");
  const status =
    event.type === "customer.subscription.deleted"
      ? "canceled"
      : mapStripeStatus(sub.status);

  const admin = createAdminClient();
  if (!admin) {
    return NextResponse.json({ error: "service role not configured" }, { status: 501 });
  }

  const { error } = await admin.from("subscriptions").upsert(
    {
      org_id: orgId, // explicit — service role has no RLS safety net
      stripe_customer_id: sub.customer,
      stripe_subscription_id: sub.id,
      tier,
      status,
      current_period_start: tsToIso(sub.current_period_start),
      current_period_end: tsToIso(sub.current_period_end),
    },
    { onConflict: "org_id" },
  );
  if (error) {
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ received: true });
}

function tsToIso(ts: number | undefined): string | null {
  return ts ? new Date(ts * 1000).toISOString() : null;
}

/** Stripe signature scheme: HMAC-SHA256 of `${t}.${payload}` with the secret. */
function verifySignature(payload: string, header: string, secret: string): boolean {
  const parts = new Map(
    header.split(",").map((kv) => {
      const [k, ...rest] = kv.split("=");
      return [k, rest.join("=")] as const;
    }),
  );
  const t = parts.get("t");
  const v1 = parts.get("v1");
  if (!t || !v1) return false;

  // Reject stale events (replay defence, 5-minute tolerance).
  const age = Math.abs(Date.now() / 1000 - Number(t));
  if (!Number.isFinite(age) || age > 300) return false;

  const expected = createHmac("sha256", secret)
    .update(`${t}.${payload}`)
    .digest("hex");
  const a = Buffer.from(expected, "hex");
  const b = Buffer.from(v1, "hex");
  return a.length === b.length && timingSafeEqual(a, b);
}

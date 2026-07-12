import { Check, ExternalLink } from "lucide-react";
import { requireContext, getPlans, getUsageSummary } from "@/lib/data";
import { PageHeader } from "@/components/page-header";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { buttonClasses } from "@/components/ui/button";
import { QuotaMeter } from "@/components/quota-meter";
import { TIER_DISPLAY, frameworksLabel } from "@/lib/entitlements";
import {
  cn,
  formatCents,
  formatDate,
  formatDateTime,
  formatTokens,
} from "@/lib/utils";
import type { Tier } from "@/lib/types";

export const metadata = { title: "Billing & Plan" };

const TIER_RANK: Record<Tier, number> = {
  free: 0,
  hobby: 1,
  pro: 2,
  design: 3,
  enterprise: 4,
};

export default async function BillingPage(props: PageProps<"/billing">) {
  const search = await props.searchParams;
  const ctx = await requireContext();
  const [plans, usage] = await Promise.all([
    getPlans(),
    getUsageSummary(ctx.org.id, null),
  ]);

  const notice =
    search.success === "1"
      ? { tone: "ok" as const, text: "Checkout complete — your plan updates as soon as the Stripe webhook lands (usually seconds)." }
      : search.canceled === "1"
        ? { tone: "warn" as const, text: "Checkout canceled — no changes made." }
        : search.notice === "stripe-unconfigured"
          ? { tone: "warn" as const, text: "Stripe is not configured on the server yet. Set STRIPE_SECRET_KEY and the STRIPE_PRICE_* env vars (README.md)." }
          : search.notice === "demo"
            ? { tone: "warn" as const, text: "Demo mode — billing actions are disabled." }
            : null;

  const isOwner = ctx.role === "owner" || ctx.role === "admin";

  return (
    <>
      <PageHeader
        title="Billing & Plan"
        description="Subscription state syncs from Stripe webhooks — the database is the source of truth."
      />

      {notice && (
        <p
          className={cn(
            "mb-5 rounded-xl border px-4 py-3 text-xs",
            notice.tone === "ok"
              ? "border-brand/30 bg-brand/10 text-brand"
              : "border-amber-500/30 bg-amber-500/10 text-amber-300",
          )}
        >
          {notice.text}
        </p>
      )}

      {/* Current plan + usage */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Current plan</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-2xl font-semibold capitalize tracking-tight">
              {ctx.quota.tier}
              <Badge className="ml-2 align-middle capitalize">
                {ctx.subscription.status}
              </Badge>
            </p>
            <dl className="space-y-1.5 text-xs text-ink-dim">
              <div className="flex justify-between">
                <dt>Reasoning model</dt>
                <dd className="font-mono">{ctx.quota.model}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Period ends</dt>
                <dd>{formatDate(ctx.subscription.current_period_end)}</dd>
              </div>
            </dl>
            {isOwner && ctx.subscription.stripe_customer_id && (
              <a
                href="/api/billing/portal"
                className={`${buttonClasses("secondary", "sm")} w-full`}
              >
                Manage in Stripe portal <ExternalLink size={12} />
              </a>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Usage this period</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <QuotaMeter quota={ctx.quota} />
            <dl className="space-y-1.5 text-xs text-ink-dim">
              <div className="flex justify-between">
                <dt>Tokens through Layer 3</dt>
                <dd className="font-mono">{formatTokens(usage.periodTokens)}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Model spend</dt>
                <dd className="font-mono">{formatCents(usage.periodCostCents)}</dd>
              </div>
            </dl>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent usage events</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {usage.events.length === 0 && (
                <li className="py-4 text-center text-xs text-ink-faint">
                  No usage yet this period.
                </li>
              )}
              {usage.events.slice(0, 5).map((e) => (
                <li
                  key={e.id}
                  className="flex items-center justify-between gap-2 text-xs"
                >
                  <Badge className="uppercase">{e.kind}</Badge>
                  <span className="min-w-0 flex-1 truncate font-mono text-[10px] text-ink-faint">
                    {e.model ?? ""}
                  </span>
                  <span className="text-ink-faint">
                    {formatDateTime(e.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      {/* Plans */}
      <h2 className="mb-4 mt-10 text-sm font-semibold uppercase tracking-wider text-ink-faint">
        Change plan
      </h2>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {plans.map((plan) => {
          const d = TIER_DISPLAY[plan.tier];
          const current = plan.tier === ctx.quota.tier;
          const upgrade = TIER_RANK[plan.tier] > TIER_RANK[ctx.quota.tier];
          return (
            <Card
              key={plan.tier}
              className={cn(
                "flex flex-col",
                current && "border-brand/40 bg-brand/5",
              )}
            >
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>{d.name}</CardTitle>
                  {current && (
                    <Badge className="border-brand/30 bg-brand/10 text-brand">
                      Current
                    </Badge>
                  )}
                </div>
                <CardDescription>
                  {d.priceMonthly == null ? "Custom pricing" : `$${d.priceMonthly}/mo`}
                  {" · "}
                  {plan.scans_per_month == null
                    ? "custom quota"
                    : `${plan.scans_per_month} scans`}
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-1 flex-col gap-4">
                <ul className="flex-1 space-y-2 text-xs text-ink-dim">
                  <Feature>Model: {plan.llm_model}</Feature>
                  <Feature>{frameworksLabel(plan.frameworks)}</Feature>
                  <Feature>
                    {plan.seats == null ? "Custom seats" : `${plan.seats} seats`}
                  </Feature>
                  {plan.api_access && <Feature>API access</Feature>}
                  {plan.sso && <Feature>SSO / SAML</Feature>}
                  {plan.sla && <Feature>SLA-backed support</Feature>}
                </ul>
                {current ? (
                  <span className="text-center text-[11px] text-ink-faint">
                    Your team is on this plan
                  </span>
                ) : plan.tier === "enterprise" ? (
                  <a
                    href="mailto:sales@adcoherentlabs.com"
                    className={`${buttonClasses("secondary", "sm")} w-full`}
                  >
                    Contact sales
                  </a>
                ) : plan.tier === "free" ? (
                  <span className="text-center text-[11px] text-ink-faint">
                    Downgrade via the Stripe portal
                  </span>
                ) : (
                  <a
                    href={`/api/billing/checkout?tier=${plan.tier}`}
                    className={`${buttonClasses(upgrade ? "primary" : "secondary", "sm")} w-full`}
                  >
                    {upgrade ? "Upgrade" : "Switch"}
                  </a>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
      <p className="mt-4 text-[11px] text-ink-faint">
        Entitlements are enforced server-side from the subscription record —
        never from the client (playbook Phase 6).
      </p>
    </>
  );
}

function Feature({ children }: { children: React.ReactNode }) {
  return (
    <li className="flex gap-2">
      <Check size={13} className="mt-0.5 shrink-0 text-brand" />
      <span>{children}</span>
    </li>
  );
}

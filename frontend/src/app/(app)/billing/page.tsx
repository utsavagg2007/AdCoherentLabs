"use client";

/** Billing & credits: live balance, ledger, per-run price list, Stripe
 * checkout/portal redirects. No invented dollar prices; monthly checkout only
 * (annual pricing isn't implemented server-side, so it's never offered). */

import { useState } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  CircleDollarSign,
  ExternalLink,
  Package,
  ReceiptText,
  Sparkles,
} from "lucide-react";
import { PageBody, PageHeader } from "@/components/app/page-header";
import { useApi, useOrg } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorPanel, Skeleton } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import { describeError, isApiError } from "@/lib/api";
import { useAsyncData } from "@/lib/hooks";
import { LEDGER_REASON_LABEL } from "@/lib/labels";
import { CREDIT_PACKS, PLANS } from "@/lib/plans";
import type { LedgerEntry } from "@/lib/types";
import { cn, formatDate, formatDateTime, formatNumber } from "@/lib/utils";

export default function BillingPage() {
  const api = useApi();
  const { orgId, role } = useOrg();
  const { toast } = useToast();

  const orgMe = useAsyncData((s) => api.orgMe(s), [api, orgId]);
  const credits = useAsyncData((s) => api.credits(s), [api, orgId]);
  const [extraLedger, setExtraLedger] = useState<LedgerEntry[]>([]);
  const [nextBeforeId, setNextBeforeId] = useState<number | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const ledger = useAsyncData(
    async (s) => {
      const page = await api.creditLedger(null, 25, s);
      setExtraLedger([]);
      setNextBeforeId(page.next_before_id);
      return page;
    },
    [api, orgId]
  );
  const [busyAction, setBusyAction] = useState<string | null>(null);

  const isAdmin = role === "admin" || role === "owner";
  const tier = orgMe.data?.tier;
  const packsAllowed = Boolean(orgMe.data?.entitlements.credit_packs_allowed);

  function surfaceBillingError(e: unknown) {
    if (isApiError(e) && e.status === 503) {
      toast({
        kind: "info",
        title: "Billing isn't configured in this environment",
        detail:
          "Stripe isn't wired up here yet — checkout and the portal will activate once it is.",
      });
      return;
    }
    const d = describeError(e);
    toast({ kind: "error", title: d.title, detail: d.detail });
  }

  async function checkout(tierId: "hobby" | "pro" | "design" | "enterprise") {
    setBusyAction(`plan:${tierId}`);
    try {
      const { checkout_url } = await api.subscriptionCheckout(tierId);
      window.location.assign(checkout_url);
    } catch (e) {
      surfaceBillingError(e);
      setBusyAction(null);
    }
  }

  async function buyPack(pack: "starter" | "growth" | "scale") {
    setBusyAction(`pack:${pack}`);
    try {
      const { checkout_url } = await api.packCheckout(pack);
      window.location.assign(checkout_url);
    } catch (e) {
      surfaceBillingError(e);
      setBusyAction(null);
    }
  }

  async function openPortal() {
    setBusyAction("portal");
    try {
      const { portal_url } = await api.billingPortal();
      window.location.assign(portal_url);
    } catch (e) {
      surfaceBillingError(e);
      setBusyAction(null);
    }
  }

  const allLedger = [...(ledger.data?.ledger ?? []), ...extraLedger];

  async function loadMoreLedger() {
    if (!nextBeforeId) return;
    setLoadingMore(true);
    try {
      const page = await api.creditLedger(nextBeforeId, 25);
      setExtraLedger((p) => [...p, ...page.ledger]);
      setNextBeforeId(page.ledger.length ? page.next_before_id : null);
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Billing & credits"
        description="Credits meter every review. Plans set the monthly allowance; packs top it up."
        actions={
          isAdmin ? (
            <Button
              variant="secondary"
              onClick={openPortal}
              loading={busyAction === "portal"}
            >
              <ExternalLink className="size-4" aria-hidden />
              Billing portal
            </Button>
          ) : undefined
        }
      />
      <PageBody>
        {orgMe.error ? (
          <ErrorPanel error={orgMe.error} onRetry={() => orgMe.refresh()} />
        ) : (
          <div className="space-y-8">
            {/* balance + plan row */}
            <div className="grid gap-4 lg:grid-cols-3">
              <div className="card p-5">
                <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-wider text-zinc-400 uppercase">
                  <CircleDollarSign className="size-3.5" aria-hidden />
                  Balance
                </p>
                {credits.loading ? (
                  <Skeleton className="mt-2 h-9 w-28" />
                ) : (
                  <>
                    <p className="mt-1.5 text-4xl font-extrabold text-ink-900 tabular-nums">
                      {formatNumber(credits.data?.total)}
                    </p>
                    <dl className="mt-3 space-y-1 text-[12.5px] text-zinc-500 tabular-nums">
                      <div className="flex justify-between">
                        <dt>Subscription credits</dt>
                        <dd className="font-bold text-ink-800">
                          {formatNumber(credits.data?.subscription_credits)}
                        </dd>
                      </div>
                      <div className="flex justify-between">
                        <dt>Purchased credits</dt>
                        <dd className="font-bold text-ink-800">
                          {formatNumber(credits.data?.purchased_credits)}
                        </dd>
                      </div>
                      {credits.data?.cycle_end && (
                        <div className="flex justify-between border-t border-line pt-1.5">
                          <dt>Allowance resets</dt>
                          <dd className="font-bold text-ink-800">
                            {formatDate(credits.data.cycle_end)}
                          </dd>
                        </div>
                      )}
                    </dl>
                    <p className="mt-3 text-[11.5px] leading-relaxed text-zinc-400">
                      Subscription credits spend first and reset each cycle;
                      purchased credits never expire.
                    </p>
                  </>
                )}
              </div>

              <div className="card p-5">
                <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-wider text-zinc-400 uppercase">
                  <Sparkles className="size-3.5" aria-hidden />
                  Current plan
                </p>
                {orgMe.loading ? (
                  <Skeleton className="mt-2 h-9 w-24" />
                ) : (
                  <>
                    <p className="mt-1.5 text-4xl font-extrabold text-ink-900 capitalize">
                      {tier}
                    </p>
                    <dl className="mt-3 space-y-1 text-[12.5px] text-zinc-500 tabular-nums">
                      <div className="flex justify-between">
                        <dt>Monthly allowance</dt>
                        <dd className="font-bold text-ink-800">
                          {orgMe.data?.entitlements.credits_per_month != null
                            ? formatNumber(orgMe.data.entitlements.credits_per_month)
                            : "Custom"}
                        </dd>
                      </div>
                      <div className="flex justify-between">
                        <dt>Upload cap</dt>
                        <dd className="font-bold text-ink-800">
                          {orgMe.data?.entitlements.max_upload_mb} MB
                        </dd>
                      </div>
                      <div className="flex justify-between">
                        <dt>Seats</dt>
                        <dd className="font-bold text-ink-800">
                          {orgMe.data?.entitlements.seats ?? "Custom"}
                        </dd>
                      </div>
                      <div className="flex justify-between">
                        <dt>API access</dt>
                        <dd className="font-bold text-ink-800">
                          {orgMe.data?.entitlements.api_access ? "Yes" : "No"}
                        </dd>
                      </div>
                    </dl>
                  </>
                )}
              </div>

              {/* price list */}
              <div className="card p-5">
                <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-wider text-zinc-400 uppercase">
                  <ReceiptText className="size-3.5" aria-hidden />
                  Cost per review
                </p>
                {credits.loading ? (
                  <Skeleton className="mt-2 h-24" />
                ) : (
                  <>
                    <dl className="mt-3 space-y-1.5 text-[13px] tabular-nums">
                      {[
                        ["Text", credits.data?.price_list.text],
                        ["Image", credits.data?.price_list.image],
                        ["HTML", credits.data?.price_list.html],
                        ["Extra carousel card", credits.data?.price_list.carousel_card],
                      ].map(([label, value]) => (
                        <div
                          key={label as string}
                          className="flex items-center justify-between rounded-lg bg-cream px-3 py-2"
                        >
                          <dt className="font-semibold text-zinc-600">{label}</dt>
                          <dd className="font-extrabold text-violet-700">
                            {value != null ? `${value} cr` : "—"}
                          </dd>
                        </div>
                      ))}
                    </dl>
                    <p className="mt-3 text-[11.5px] leading-relaxed text-zinc-400">
                      This live price list is exactly what the platform
                      enforces. A carousel costs the image price plus each
                      extra card.
                    </p>
                  </>
                )}
              </div>
            </div>

            {/* credit packs */}
            <section aria-label="Credit packs">
              <h2 className="mb-3 text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
                Credit packs
              </h2>
              {!packsAllowed ? (
                <div className="rounded-2xl border border-dashed border-zinc-300 bg-cream/60 p-5 text-[13.5px] leading-relaxed text-zinc-500">
                  Credit packs are available on paid plans. Upgrade below to
                  top up beyond your monthly allowance — purchased credits
                  never expire.
                </div>
              ) : !isAdmin ? (
                <div className="rounded-2xl border border-dashed border-zinc-300 bg-cream/60 p-5 text-[13.5px] leading-relaxed text-zinc-500">
                  An admin or owner purchases credit packs for this workspace.
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-3">
                  {CREDIT_PACKS.map((p) => (
                    <div key={p.id} className="card flex items-center gap-3 p-4">
                      <span className="flex size-10 items-center justify-center rounded-xl border border-violet-200 bg-violet-50 text-violet-600">
                        <Package className="size-4.5" aria-hidden />
                      </span>
                      <span className="flex-1 text-[14px] font-bold text-ink-900">
                        {p.name}
                      </span>
                      <Button
                        size="sm"
                        variant="secondary"
                        loading={busyAction === `pack:${p.id}`}
                        onClick={() => buyPack(p.id)}
                      >
                        Buy
                      </Button>
                    </div>
                  ))}
                  <p className="text-[11.5px] leading-relaxed text-zinc-400 sm:col-span-3">
                    Pack sizes and prices are shown at Stripe checkout; credits
                    land in your purchased balance on payment.
                  </p>
                </div>
              )}
            </section>

            {/* plans */}
            <section aria-label="Plans">
              <h2 className="mb-3 text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
                Plans
              </h2>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                {PLANS.map((p) => {
                  const current = p.tier === tier;
                  return (
                    <div
                      key={p.tier}
                      className={cn(
                        "flex flex-col rounded-2xl border bg-white p-4",
                        current
                          ? "border-violet-300 shadow-[0_0_0_3px_rgb(139_92_246/0.12)]"
                          : "border-line"
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <h3 className="text-[14px] font-extrabold text-ink-900">
                          {p.name}
                        </h3>
                        {current && (
                          <span className="rounded-full bg-violet-600 px-2 py-0.5 text-[10px] font-bold tracking-wider text-white uppercase">
                            Current
                          </span>
                        )}
                      </div>
                      <p className="mt-1.5 text-[13px] font-bold text-violet-700 tabular-nums">
                        {p.monthlyCredits != null
                          ? `${formatNumber(p.monthlyCredits)} credits/mo`
                          : "Custom credits"}
                      </p>
                      <p className="mt-1 flex-1 text-[11.5px] leading-relaxed text-zinc-500">
                        {p.uploadCapMb} MB uploads ·{" "}
                        {p.seats != null ? `${p.seats} seat${p.seats > 1 ? "s" : ""}` : "custom seats"}{" "}
                        · {p.apiAccess ? "API" : "no API"}
                      </p>
                      <div className="mt-3">
                        {current ? (
                          <Button variant="secondary" size="sm" className="w-full" disabled>
                            Your plan
                          </Button>
                        ) : p.tier === "enterprise" ? (
                          <a
                            href="mailto:sales@adcoherentlabs.com?subject=Enterprise%20plan"
                            className="btn-secondary w-full !py-1.5 !text-[12.5px]"
                          >
                            Talk to sales
                          </a>
                        ) : p.tier === "free" ? (
                          <Button variant="secondary" size="sm" className="w-full" disabled>
                            Downgrade via portal
                          </Button>
                        ) : isAdmin ? (
                          <Button
                            size="sm"
                            className="w-full"
                            loading={busyAction === `plan:${p.tier}`}
                            onClick={() =>
                              checkout(p.tier as "hobby" | "pro" | "design")
                            }
                          >
                            Choose {p.name}
                          </Button>
                        ) : (
                          <Button variant="secondary" size="sm" className="w-full" disabled>
                            Ask an admin
                          </Button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
              <p className="mt-3 text-[11.5px] leading-relaxed text-zinc-400">
                Checkout is monthly through Stripe — prices are shown there.
                Plan changes and cancellation live in the billing portal. If
                your account uses MFA, these actions may ask you to
                re-authenticate first.
              </p>
            </section>

            {/* ledger */}
            <section aria-label="Credit ledger">
              <h2 className="mb-3 text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
                Credit ledger
              </h2>
              {ledger.error ? (
                <ErrorPanel error={ledger.error} onRetry={() => ledger.refresh()} />
              ) : ledger.loading ? (
                <Skeleton className="h-40" />
              ) : allLedger.length === 0 ? (
                <EmptyState
                  title="No ledger entries yet"
                  description="Every grant, charge, and refund lands here — the same record an auditor reads."
                />
              ) : (
                <div className="card overflow-x-auto">
                  <table className="w-full min-w-[560px] text-left">
                    <thead>
                      <tr className="border-b border-line text-[11px] font-bold tracking-wider text-zinc-400 uppercase">
                        <th className="px-4 py-3">Entry</th>
                        <th className="px-4 py-3">Bucket</th>
                        <th className="px-4 py-3 text-right">Change</th>
                        <th className="px-4 py-3 text-right">Balance after</th>
                        <th className="px-4 py-3">When</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {allLedger.map((e) => (
                        <tr key={e.id} className="text-[13px]">
                          <td className="px-4 py-3">
                            <span className="font-bold text-ink-900">
                              {LEDGER_REASON_LABEL[e.reason] ?? e.reason}
                            </span>
                            {e.run_id && (
                              <a
                                href={`/runs/${e.run_id}`}
                                className="ml-2 font-mono text-[11px] font-semibold text-violet-700 hover:text-violet-900"
                              >
                                {e.run_id.slice(0, 8)}
                              </a>
                            )}
                          </td>
                          <td className="px-4 py-3 text-[12px] text-zinc-500 capitalize">
                            {e.bucket}
                          </td>
                          <td
                            className={cn(
                              "px-4 py-3 text-right font-bold tabular-nums",
                              e.delta > 0 ? "text-emerald-700" : "text-ink-800"
                            )}
                          >
                            <span className="inline-flex items-center gap-1">
                              {e.delta > 0 ? (
                                <ArrowUpRight className="size-3.5" aria-hidden />
                              ) : (
                                <ArrowDownRight className="size-3.5 text-zinc-400" aria-hidden />
                              )}
                              {e.delta > 0 ? "+" : ""}
                              {formatNumber(e.delta)}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right text-zinc-500 tabular-nums">
                            {formatNumber(e.balance_after)}
                          </td>
                          <td className="px-4 py-3 text-[12px] whitespace-nowrap text-zinc-500">
                            {formatDateTime(e.created_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {nextBeforeId && (
                    <div className="border-t border-line p-3 text-center">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={loadMoreLedger}
                        loading={loadingMore}
                      >
                        Load older entries
                      </Button>
                    </div>
                  )}
                </div>
              )}
            </section>
          </div>
        )}
      </PageBody>
    </>
  );
}

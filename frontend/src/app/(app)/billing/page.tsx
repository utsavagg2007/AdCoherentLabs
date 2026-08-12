"use client";

/** Billing & credits: live balance, ledger, per-run price list, plans and
 * packs — every price on this page comes from GET /v1/plans (backend-owned).
 * Checkout redirects to Stripe when configured; in dev the backend simulates
 * checkout and returns here with ?status=…&simulated=1. */

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
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
import { CREDITS_REFRESH_EVENT } from "@/components/app/sidebar";
import { useApi, useOrg } from "@/components/providers";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorPanel, Skeleton } from "@/components/ui/feedback";
import { useToast } from "@/components/ui/toast";
import { describeError, isApiError } from "@/lib/api";
import { useAsyncData } from "@/lib/hooks";
import { LEDGER_REASON_LABEL } from "@/lib/labels";
import type { LedgerEntry } from "@/lib/types";
import { cn, formatDate, formatDateTime, formatNumber } from "@/lib/utils";

function usd(cents: number | null | undefined): string {
  if (cents == null) return "Custom";
  if (cents === 0) return "$0";
  return `$${(cents / 100).toLocaleString("en-US", {
    maximumFractionDigits: cents % 100 === 0 ? 0 : 2,
  })}`;
}

export default function BillingPage() {
  return (
    <Suspense>
      <BillingContent />
    </Suspense>
  );
}

function BillingContent() {
  const api = useApi();
  const { orgId, role } = useOrg();
  const { toast } = useToast();
  const router = useRouter();
  const searchParams = useSearchParams();

  const orgMe = useAsyncData((s) => api.orgMe(s), [api, orgId]);
  const credits = useAsyncData((s) => api.credits(s), [api, orgId]);
  const plans = useAsyncData((s) => api.plans(s), [api]);
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
  const priceList = credits.data?.price_list;
  const myTokenRate = plans.data?.token_rates.find((r) => r.tier === tier);

  // checkout return (Stripe or the dev simulator) — toast + refresh once
  useEffect(() => {
    const status = searchParams.get("status");
    if (!status) return;
    const simulated = searchParams.get("simulated") === "1";
    if (status === "success") {
      toast({
        kind: "success",
        title: simulated
          ? "Plan activated (dev checkout simulation)"
          : "Subscription updated",
        detail: "Your allowance grants on the new plan's cycle.",
      });
    } else if (status === "pack_success") {
      toast({
        kind: "success",
        title: simulated
          ? "Credit pack granted (dev checkout simulation)"
          : "Credit pack purchased",
        detail: "The credits are in your purchased balance.",
      });
    } else if (status === "cancelled") {
      toast({ kind: "info", title: "Checkout cancelled — nothing changed" });
    }
    orgMe.refresh({ silent: true });
    credits.refresh({ silent: true });
    ledger.refresh({ silent: true });
    window.dispatchEvent(new Event(CREDITS_REFRESH_EVENT));
    router.replace("/billing", { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

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
    if (isApiError(e) && e.status === 403) {
      toast({
        kind: "info",
        title: "Not available on this plan",
        detail: e.message,
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
                <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-wider text-ink-500 uppercase">
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
                    <dl className="mt-3 space-y-1 text-[12.5px] text-ink-500 tabular-nums">
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
                      {/* Without this line a user watching their balance dip
                          while a run is in flight has no way to know why. */}
                      {!!credits.data?.held && (
                        <div className="flex justify-between">
                          <dt>Reserved by running reviews</dt>
                          <dd className="font-bold text-ink-800">
                            {formatNumber(credits.data.held)}
                          </dd>
                        </div>
                      )}
                      {credits.data?.cycle_end && (
                        <div className="flex justify-between border-t border-line pt-1.5">
                          <dt>Allowance resets</dt>
                          <dd className="font-bold text-ink-800">
                            {formatDate(credits.data.cycle_end)}
                          </dd>
                        </div>
                      )}
                    </dl>
                    <p className="mt-3 text-[11.5px] leading-relaxed text-ink-500">
                      Subscription credits spend first and reset each cycle;
                      purchased credits never expire.
                      {!!credits.data?.held &&
                        " Credits reserved by a running review are already" +
                          " deducted here; whatever it does not use comes back" +
                          " when it finishes."}
                    </p>
                  </>
                )}
              </div>

              <div className="card p-5">
                <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-wider text-ink-500 uppercase">
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
                    <dl className="mt-3 space-y-1 text-[12.5px] text-ink-500 tabular-nums">
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
                        <dt>Media</dt>
                        <dd className="font-bold text-ink-800">
                          {orgMe.data?.entitlements.allowed_kinds?.includes("video")
                            ? orgMe.data?.entitlements.max_video_seconds != null
                              ? `All · video ≤ ${orgMe.data.entitlements.max_video_seconds}s`
                              : "All formats"
                            : "Docs & images"}
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
                <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-wider text-ink-500 uppercase">
                  <ReceiptText className="size-3.5" aria-hidden />
                  Cost per review
                </p>
                {credits.loading ? (
                  <Skeleton className="mt-2 h-24" />
                ) : (
                  <>
                    <dl className="mt-3 space-y-1.5 text-[13px] tabular-nums">
                      {(
                        [
                          ["Text", priceList?.text],
                          ["Image", priceList?.image],
                          ["PDF", priceList?.pdf],
                          ["Document", priceList?.docx],
                          ["Video", priceList?.video],
                          ["Extra carousel card", priceList?.carousel_card],
                        ] as const
                      )
                        .filter(([, v]) => v != null)
                        .map(([label, value]) => (
                          <div
                            key={label}
                            className="flex items-center justify-between rounded-lg bg-coal-700 px-3 py-1.5"
                          >
                            <dt className="font-semibold text-ink-600">{label}</dt>
                            <dd className="font-extrabold text-ink-900">
                              {value} cr
                            </dd>
                          </div>
                        ))}
                    </dl>
                    <p className="mt-3 text-[11.5px] leading-relaxed text-ink-500">
                      Minimum price of a run — credits are reserved when it
                      starts, metered as the engine works, and the unused
                      remainder is returned when it finishes.
                      {myTokenRate
                        ? ` Model usage is charged at ${myTokenRate.in_per_1k}/${myTokenRate.out_per_1k} credits per 1k input/output tokens.`
                        : " Model usage is charged from actual tokens."}
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
                <div className="rounded-2xl border border-dashed border-white/15 bg-coal-850 p-5 text-[13.5px] leading-relaxed text-ink-500">
                  Credit packs require an active paid plan. Upgrade below to
                  top up beyond your monthly allowance — purchased credits
                  never expire.
                </div>
              ) : !isAdmin ? (
                <div className="rounded-2xl border border-dashed border-white/15 bg-coal-850 p-5 text-[13.5px] leading-relaxed text-ink-500">
                  An admin or owner purchases credit packs for this workspace.
                </div>
              ) : (
                <div className="grid gap-3 sm:grid-cols-3">
                  {(plans.data?.packs ?? []).map((p) => (
                    <div key={p.pack} className="card flex items-center gap-3 p-4">
                      <span className="flex size-10 items-center justify-center rounded-xl border border-white/15 bg-white/6 text-ink-600">
                        <Package className="size-4.5" aria-hidden />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[14px] font-bold text-ink-900 capitalize">
                          {p.pack} · {formatNumber(p.credits)} cr
                        </span>
                        <span className="block text-[12px] text-ink-500">
                          {usd(p.usd_cents)} one-time
                        </span>
                      </span>
                      <Button
                        size="sm"
                        variant="secondary"
                        loading={busyAction === `pack:${p.pack}`}
                        onClick={() =>
                          buyPack(p.pack as "starter" | "growth" | "scale")
                        }
                      >
                        Buy
                      </Button>
                    </div>
                  ))}
                  <p className="text-[11.5px] leading-relaxed text-ink-500 sm:col-span-3">
                    Prices are published by the platform; credits land in your
                    purchased balance on payment.
                  </p>
                </div>
              )}
            </section>

            {/* plans */}
            <section aria-label="Plans">
              <h2 className="mb-3 text-[13px] font-extrabold tracking-wide text-ink-900 uppercase">
                Plans
              </h2>
              {plans.error ? (
                <ErrorPanel error={plans.error} onRetry={() => plans.refresh()} />
              ) : plans.loading ? (
                <Skeleton className="h-40" />
              ) : (
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
                  {(plans.data?.plans ?? []).map((p) => {
                    const current = p.tier === tier;
                    return (
                      <div
                        key={p.tier}
                        className={cn(
                          "flex flex-col rounded-2xl border bg-coal-800 p-4",
                          current
                            ? "border-white/25 ring-1 ring-white/10"
                            : "border-line"
                        )}
                      >
                        <div className="flex items-center justify-between">
                          <h3 className="text-[14px] font-extrabold text-ink-900">
                            {p.name}
                          </h3>
                          {current && (
                            <span className="rounded-full border border-white/20 bg-white/10 px-2 py-0.5 text-[10px] font-bold tracking-wider text-ink-900 uppercase">
                              Current
                            </span>
                          )}
                        </div>
                        <p className="mt-1.5 text-xl font-extrabold text-ink-900 tabular-nums">
                          {usd(p.monthly_usd_cents)}
                          {p.monthly_usd_cents != null && (
                            <span className="text-[12px] font-semibold text-ink-500">
                              /mo
                            </span>
                          )}
                        </p>
                        <p className="mt-1 text-[13px] font-bold text-ink-800 tabular-nums">
                          {p.credits_per_month != null
                            ? `${formatNumber(p.credits_per_month)} credits/mo`
                            : "Custom credits"}
                        </p>
                        <p className="mt-1 flex-1 text-[11.5px] leading-relaxed text-ink-500">
                          {p.max_upload_mb} MB uploads ·{" "}
                          {p.seats != null
                            ? `${p.seats} seat${p.seats > 1 ? "s" : ""}`
                            : "custom seats"}{" "}
                          · {p.api_access ? "API" : "no API"} ·{" "}
                          {p.allowed_kinds.includes("video")
                            ? p.max_video_seconds != null
                              ? `video ≤ ${p.max_video_seconds}s`
                              : "full video"
                            : "no video"}
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
              )}
              <p className="mt-3 text-[11.5px] leading-relaxed text-ink-500">
                Prices are published live by the platform. Plan changes and
                cancellation live in the billing portal. If your account uses
                MFA, these actions may ask you to re-authenticate first.
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
                      <tr className="border-b border-line text-[11px] font-bold tracking-wider text-ink-500 uppercase">
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
                                className="ml-2 font-mono text-[11px] font-semibold text-ink-900 hover:text-white"
                              >
                                {e.run_id.slice(0, 8)}
                              </a>
                            )}
                          </td>
                          <td className="px-4 py-3 text-[12px] text-ink-500 capitalize">
                            {e.bucket}
                          </td>
                          <td
                            className={cn(
                              "px-4 py-3 text-right font-bold tabular-nums",
                              e.delta > 0 ? "text-emerald-300" : "text-ink-800"
                            )}
                          >
                            <span className="inline-flex items-center gap-1">
                              {e.delta > 0 ? (
                                <ArrowUpRight className="size-3.5" aria-hidden />
                              ) : (
                                <ArrowDownRight className="size-3.5 text-ink-500" aria-hidden />
                              )}
                              {e.delta > 0 ? "+" : ""}
                              {formatNumber(e.delta)}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right text-ink-500 tabular-nums">
                            {formatNumber(e.balance_after)}
                          </td>
                          <td className="px-4 py-3 text-[12px] whitespace-nowrap text-ink-500">
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

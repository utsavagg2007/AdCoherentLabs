"use client";

/** Credit metering, made legible.
 *
 * The engine charges `max(floor, Σ effort × rate)` against an escrow that is
 * reserved before the run starts. Three numbers therefore move at different
 * times — reserved, metered, charged — and a balance that dips mid-run and
 * partially recovers afterwards is alarming unless the UI narrates it.
 *
 * Everything here reads live rates from the API. Nothing is hardcoded, so
 * these surfaces stay correct when ops retunes the rate card. */

import { Coins, Cpu, Info, TrendingDown } from "lucide-react";
import { EFFORT_UNIT_LABEL } from "@/lib/labels";
import type {
  CreditBalance,
  EffortRates,
  RunCredits,
  RunEffort,
} from "@/lib/types";
import { cn, formatNumber } from "@/lib/utils";

/** Credits are integers when charged but fractional while metering. Show
 * enough precision to see a meter move without implying false accuracy. */
export function formatCredits(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (Number.isInteger(n)) return n.toLocaleString();
  if (Math.abs(n) < 10) return n.toFixed(2).replace(/\.?0+$/, "");
  return Math.round(n).toLocaleString();
}

// ─────────────────────────────────────────────────────────── balance meter

/** Stacked meter over the monthly allowance: what is spendable, what a
 * running review has escrowed, and what is already gone this cycle.
 *
 * Renders as three labelled segments plus a legend, so the split survives
 * both colorblindness and a greyscale print of the billing page. */
export function CreditMeter({
  credits,
  className,
}: {
  credits: CreditBalance;
  className?: string;
}) {
  const allowance = credits.credits_per_month;
  const available = Math.max(0, credits.total);
  const held = Math.max(0, credits.held ?? 0);

  // Without a published allowance (enterprise/custom) there is no denominator
  // to fill, so scale the bar to what the org is actually holding instead.
  const denominator = allowance ?? Math.max(available + held, 1);
  const spent = allowance != null ? Math.max(0, allowance - available - held) : 0;

  const pct = (v: number) => `${Math.min(100, (v / denominator) * 100)}%`;

  const segments = [
    { key: "available", label: "Available", value: available, cls: "bg-brand" },
    { key: "held", label: "Reserved by runs", value: held, cls: "bg-accent" },
    { key: "spent", label: "Spent this cycle", value: spent, cls: "bg-tint-3" },
  ].filter((s) => s.value > 0 || s.key === "available");

  return (
    <div className={className}>
      <div
        className="flex h-2.5 w-full overflow-hidden rounded-full bg-sunken"
        role="img"
        aria-label={
          `${formatCredits(available)} credits available` +
          (held > 0 ? `, ${formatCredits(held)} reserved by running reviews` : "") +
          (allowance != null ? ` of a ${formatNumber(allowance)} monthly allowance` : "")
        }
      >
        {segments.map((s) => (
          <span
            key={s.key}
            className={cn("h-full transition-[width] duration-500", s.cls)}
            style={{ width: pct(s.value) }}
          />
        ))}
      </div>
      <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1">
        {segments.map((s) => (
          <li
            key={s.key}
            className="flex items-center gap-1.5 text-[11.5px] font-semibold text-subtle"
          >
            <span className={cn("size-2 rounded-full", s.cls)} aria-hidden />
            {s.label}
            <span className="text-body tabular-nums">{formatCredits(s.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ──────────────────────────────────────────────────────── run escrow state

const HOLD_COPY: Record<RunCredits["status"], { label: string; hint: string }> = {
  open: {
    label: "Metering",
    hint: "Credits are escrowed. Whatever this review does not use comes back when it finishes.",
  },
  settled: {
    label: "Settled",
    hint: "The review finished. It was charged for what it used; the rest was returned.",
  },
  released: {
    label: "Released",
    hint: "The review did not complete, so the whole reserve was returned.",
  },
};

/** The escrow story for one run: reserved → metered → charged, with the
 * returned remainder called out rather than left as an unexplained delta. */
export function RunCreditPanel({
  credits,
  className,
}: {
  credits: RunCredits;
  className?: string;
}) {
  const copy = HOLD_COPY[credits.status];
  const open = credits.status === "open";
  // While open, the metered figure is what has actually been consumed of the
  // escrow — that ratio is the only honest progress signal available.
  const usedPct = credits.reserved
    ? Math.min(100, (Math.max(credits.metered, credits.floor_credits) / credits.reserved) * 100)
    : 0;

  return (
    <div className={cn("card p-4", className)}>
      <div className="flex items-center justify-between gap-3">
        <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-wider text-subtle uppercase">
          <Coins className="size-3.5" aria-hidden />
          Credits
        </p>
        <span
          className={cn(
            open ? "badge-brand" : credits.status === "settled" ? "badge-pass" : "badge-neutral"
          )}
        >
          {open && (
            <span className="size-1.5 animate-pulse-dot rounded-full bg-brand" aria-hidden />
          )}
          {copy.label}
        </span>
      </div>

      <p className="mt-2.5 text-3xl font-extrabold text-strong tabular-nums">
        {formatCredits(credits.charged ?? Math.max(credits.metered, credits.floor_credits))}
        <span className="ml-1.5 text-[13px] font-bold text-subtle">
          {credits.charged == null ? `of ${formatCredits(credits.reserved)} reserved` : "charged"}
        </span>
      </p>

      {open && (
        <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-sunken">
          <div
            className="h-full rounded-full bg-[linear-gradient(90deg,var(--brand),var(--accent))] transition-[width] duration-700"
            style={{ width: `${usedPct}%` }}
          />
        </div>
      )}

      <dl className="mt-3 space-y-1 text-[12.5px] tabular-nums">
        <Row label="Base price (floor)" value={formatCredits(credits.floor_credits)} />
        <Row label="Metered usage" value={formatCredits(credits.metered)} />
        {credits.returned != null && credits.returned > 0 && (
          <Row
            label="Returned to balance"
            value={`+${formatCredits(credits.returned)}`}
            tone="pass"
          />
        )}
      </dl>

      <p className="mt-3 text-[11.5px] leading-relaxed text-subtle">{copy.hint}</p>
    </div>
  );
}

function Row({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "pass";
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-subtle">{label}</dt>
      <dd className={cn("font-bold", tone === "pass" ? "text-pass" : "text-body")}>
        {value}
      </dd>
    </div>
  );
}

// ────────────────────────────────────────────────────── effort line items

/** Where a charge actually went. Model tokens usually dominate, so they are
 * pulled to the top and given the bar; the rest is listed underneath. */
export function EffortBreakdown({
  effort,
  className,
}: {
  effort: RunEffort;
  className?: string;
}) {
  const units = [...effort.units].sort((a, b) => b.credits - a.credits);
  const total = units.reduce((sum, u) => sum + u.credits, 0);
  if (units.length === 0) return null;

  return (
    <div className={cn("card overflow-hidden", className)}>
      <div className="flex items-center gap-1.5 border-b border-line px-4 py-3">
        <Cpu className="size-3.5 text-subtle" aria-hidden />
        <h3 className="text-[11px] font-bold tracking-wider text-subtle uppercase">
          What this review used
        </h3>
      </div>
      <ul className="divide-y divide-line">
        {units.map((u) => {
          const share = total > 0 ? (u.credits / total) * 100 : 0;
          const isModel = u.unit.startsWith("llm_") || u.unit === "embed_1k";
          return (
            <li key={u.unit} className="px-4 py-3">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[13px] font-semibold text-body">
                  {EFFORT_UNIT_LABEL[u.unit] ?? u.unit}
                </span>
                <span className="text-[13px] font-extrabold text-strong tabular-nums">
                  {formatCredits(u.credits)} cr
                </span>
              </div>
              <div className="mt-1.5 flex items-center gap-2.5">
                <div className="h-1 flex-1 overflow-hidden rounded-full bg-sunken">
                  <div
                    className={cn(
                      "h-full rounded-full",
                      isModel ? "bg-brand" : "bg-accent"
                    )}
                    style={{ width: `${share}%` }}
                  />
                </div>
                <span className="shrink-0 font-mono text-[11px] text-subtle tabular-nums">
                  {formatCredits(u.quantity)} × {u.rate}
                </span>
              </div>
            </li>
          );
        })}
      </ul>
      {effort.charged != null && (
        <div className="flex items-center justify-between border-t border-line bg-sunken px-4 py-2.5">
          <span className="text-[12px] font-bold text-subtle">Charged</span>
          <span className="text-[13px] font-extrabold text-strong tabular-nums">
            {formatCredits(effort.charged)} cr
          </span>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────── the explainer

/** Plain-English pricing model, computed from the org's live rate card.
 *
 * The worked example is generated from the same rates the engine bills at,
 * so it cannot drift out of sync with what the customer is actually charged
 * the way a hand-written pricing paragraph does. */
export function MeteringExplainer({
  rates,
  floorExample,
  className,
}: {
  rates: EffortRates;
  /** Base price of a typical run on this plan, for the worked example. */
  floorExample?: number;
  className?: string;
}) {
  const inRate = rates.llm_input_1k ?? 0;
  const outRate = rates.llm_output_1k ?? 0;

  // A representative review: 40k tokens in, 6k out. Held constant so the
  // arithmetic below is checkable by hand against the published rates.
  const exampleIn = 40;
  const exampleOut = 6;
  const modelCredits = exampleIn * inRate + exampleOut * outRate;
  const floor = floorExample ?? 0;
  const charge = Math.max(floor, modelCredits);

  return (
    <div className={cn("card-brand p-5", className)}>
      <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-wider text-brand-text uppercase">
        <Info className="size-3.5" aria-hidden />
        How a review is priced
      </p>

      <p className="mt-2.5 font-mono text-[13px] leading-relaxed font-semibold text-strong">
        charge = max(base price, metered usage)
      </p>

      <p className="mt-3 text-[13px] leading-relaxed text-muted">
        Credits are escrowed when a review starts and metered as the engine
        works. Model usage is billed from the real token counts the providers
        report — input and output are priced separately, because output tokens
        cost several times what input tokens do. Whatever the review does not
        use is returned to your balance the moment it finishes.
      </p>

      <dl className="mt-4 space-y-1.5 text-[12.5px] tabular-nums">
        <div className="flex items-center justify-between rounded-lg bg-tint px-3 py-1.5">
          <dt className="font-semibold text-muted">Model input</dt>
          <dd className="font-extrabold text-strong">{inRate} cr / 1k tokens</dd>
        </div>
        <div className="flex items-center justify-between rounded-lg bg-tint px-3 py-1.5">
          <dt className="font-semibold text-muted">Model output</dt>
          <dd className="font-extrabold text-strong">{outRate} cr / 1k tokens</dd>
        </div>
      </dl>

      {(inRate > 0 || outRate > 0) && (
        <div className="mt-4 rounded-xl border border-line bg-sunken p-3">
          <p className="flex items-center gap-1.5 text-[11px] font-bold tracking-wider text-subtle uppercase">
            <TrendingDown className="size-3.5" aria-hidden />
            Worked example
          </p>
          <p className="mt-1.5 font-mono text-[12px] leading-relaxed text-muted">
            {exampleIn}k in × {inRate} + {exampleOut}k out × {outRate} ={" "}
            <span className="font-bold text-strong">
              {formatCredits(modelCredits)} cr
            </span>
            {floor > 0 && (
              <>
                {modelCredits >= floor
                  ? ` — above the ${formatCredits(floor)} cr base price, so that is the charge: `
                  : ` — under the ${formatCredits(floor)} cr base price, so the base price stands: `}
                <span className="font-bold text-strong">
                  {formatCredits(charge)} cr
                </span>
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );
}

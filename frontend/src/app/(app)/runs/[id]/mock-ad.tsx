"use client";

import { cn } from "@/lib/utils";
import type { Finding } from "@/lib/types";

/**
 * Demo-mode stand-in for the uploaded creative: a CSS-rendered fintech ad so
 * finding bounding boxes have something real to overlay.
 */
export function MockAdPreview({
  variant,
  findings,
  selectedId,
  onSelect,
}: {
  variant: "loan" | "savings";
  findings: Finding[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}) {
  return (
    <div
      className="relative aspect-square w-full select-none overflow-hidden rounded-xl border border-line bg-[#0e1a2f]"
      style={{ containerType: "inline-size" }}
    >
      {variant === "loan" ? <LoanAd /> : <SavingsAd />}

      {/* Finding overlays (bbox in 0–1 coords from Layer 1) */}
      {findings
        .filter((f) => f.location?.bbox)
        .map((f) => {
          const b = f.location!.bbox!;
          const selected = selectedId === f.id;
          return (
            <button
              key={f.id}
              type="button"
              title={`${f.framework}: ${f.message.slice(0, 80)}…`}
              onClick={() => onSelect(selected ? null : f.id)}
              className={cn(
                "absolute rounded-md border-2 transition-all",
                f.severity === "high"
                  ? "border-rose-400/80"
                  : f.severity === "medium"
                    ? "border-amber-400/80"
                    : "border-sky-400/70",
                selected
                  ? "bg-white/10 shadow-[0_0_0_4px_rgba(255,255,255,0.08)]"
                  : "bg-transparent hover:bg-white/5",
              )}
              style={{
                left: `${b.x * 100}%`,
                top: `${b.y * 100}%`,
                width: `${b.width * 100}%`,
                height: `${b.height * 100}%`,
              }}
            >
              <span
                className={cn(
                  "absolute -top-2.5 left-2 rounded px-1.5 text-[9px] font-bold uppercase leading-4",
                  f.severity === "high"
                    ? "bg-rose-400 text-rose-950"
                    : f.severity === "medium"
                      ? "bg-amber-400 text-amber-950"
                      : "bg-sky-400 text-sky-950",
                )}
              >
                {f.framework}
              </span>
            </button>
          );
        })}
    </div>
  );
}

function LoanAd() {
  return (
    <div className="flex h-full flex-col p-[6%] font-sans text-white">
      <p className="text-[2.8cqw] font-bold tracking-wide text-sky-300">
        REACH FINANCIAL
      </p>
      <h2 className="mt-[6%] text-[6.5cqw] font-extrabold leading-tight">
        Pay down debt{" "}
        <span className="text-emerald-300">8.3&times; faster</span> with Reach
        Personal Loan
      </h2>
      <div className="mt-[7%] flex gap-[4%]">
        <div className="rounded-lg bg-white/10 p-[3%]">
          <p className="text-[4.5cqw] font-bold text-emerald-300">*72%</p>
          <p className="text-[2.2cqw] text-white/80">
            Savings in total interest paid
          </p>
        </div>
        <div className="rounded-lg bg-white/10 p-[3%]">
          <p className="text-[4.5cqw] font-bold">$1,068<span className="text-[2.2cqw]">/mo</span></p>
          <p className="text-[2.2cqw] text-white/80">60-month term</p>
        </div>
      </div>
      <button className="mt-[7%] w-max rounded-full bg-emerald-400 px-[6%] py-[2.5%] text-[3cqw] font-bold text-emerald-950">
        Check your rate →
      </button>
      <p className="mt-auto text-[1.7cqw] leading-snug text-white/50">
        *Example table shows calculations based on a $40,000 Reach Personal
        Loan with a fixed rate of 20.39% APR and a 60-month term. Credit-card
        comparison assumes 25.33% average APR (Forbes, 2025). Your actual
        rate, payment amount, and total interest may vary based on your credit
        history, loan amount, and loan term.
      </p>
    </div>
  );
}

function SavingsAd() {
  return (
    <div className="flex h-full flex-col p-[6%] font-sans text-white">
      <p className="text-[2.8cqw] font-bold tracking-wide text-emerald-300">
        HIGHYIELD BANK
      </p>
      <h2 className="mt-[4%] text-[7cqw] font-extrabold leading-tight">
        Earn <span className="text-emerald-300">4.50% APY</span> on every
        dollar
      </h2>
      <p className="mt-[6%] text-[3cqw] text-white/80">
        Open in 3 minutes. FDIC-insured.
      </p>
      <p className="mt-[8%] text-[4cqw] font-bold">No fees, ever.</p>
      <button className="mt-[8%] w-max rounded-full bg-emerald-400 px-[6%] py-[2.5%] text-[3cqw] font-bold text-emerald-950">
        Start saving →
      </button>
      <p className="mt-auto text-[1.8cqw] text-white/50">
        APY accurate as of 06/01/2026. Member FDIC.
      </p>
    </div>
  );
}

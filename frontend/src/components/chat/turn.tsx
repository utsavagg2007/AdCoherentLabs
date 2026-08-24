"use client";

/**
 * The transcript primitive.
 *
 * A compliance review is a documented exchange — what was submitted, what was
 * asked, what was answered, what was decided — so it is rendered as a RECORD,
 * not as a chat. No bubbles, no avatars: a timestamp gutter, a continuous
 * hairline, and a role mark on each turn. Consecutive <Turn>s share the rule
 * because the gutter carries `border-r` and turns use padding rather than
 * margin, so the borders meet.
 *
 * That is the whole visual idea. Everything else here stays quiet.
 */

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type Role = "you" | "assistant" | "system";

const ROLE_LABEL: Record<Role, string> = {
  you: "You",
  assistant: "AdCoherent",
  system: "Record",
};

/** Stable across server and client — `toLocaleTimeString` is not. */
const TIME_FMT = new Intl.DateTimeFormat("en-US", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatTurnTime(at: Date | string): string {
  const d = typeof at === "string" ? new Date(at) : at;
  return Number.isNaN(d.getTime()) ? "--:--" : TIME_FMT.format(d);
}

export function Turn({
  role,
  at,
  working = false,
  label,
  children,
  className,
}: {
  role: Role;
  at: Date | string;
  /** Pulses the role mark while the engine is doing work. */
  working?: boolean;
  /** Overrides the role name, e.g. "AdCoherent · Layer 3". */
  label?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <article
      className={cn(
        "grid grid-cols-[3rem_minmax(0,1fr)] sm:grid-cols-[6rem_minmax(0,1fr)]",
        className
      )}
    >
      <div className="border-r border-line pt-6 pr-3 text-right sm:pr-5">
        <time
          dateTime={typeof at === "string" ? at : at.toISOString()}
          className="font-mono text-[11px] tracking-tight text-faint tabular-nums"
        >
          {formatTurnTime(at)}
        </time>
      </div>

      <div className="min-w-0 pt-6 pb-7 pl-4 sm:pl-6">
        <p className="mb-2.5 flex items-center gap-2">
          <RoleMark role={role} working={working} />
          <span className="text-[11px] font-bold tracking-[0.08em] text-subtle uppercase">
            {label ?? ROLE_LABEL[role]}
          </span>
        </p>
        <div className="min-w-0 text-[14.5px] leading-relaxed text-body">
          {children}
        </div>
      </div>
    </article>
  );
}

function RoleMark({ role, working }: { role: Role; working: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        "size-2 shrink-0 rounded-[2px]",
        role === "assistant" && "bg-brand",
        role === "you" && "bg-subtle",
        role === "system" && "bg-line-strong",
        working && "chat-mark-working"
      )}
    />
  );
}

/**
 * Scroll container for the transcript. The rule is drawn by the turns
 * themselves, so this only owns width and rhythm.
 */
export function Transcript({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto w-full max-w-[52rem] px-4 sm:px-6">{children}</div>
  );
}

/**
 * A turn's body often needs a bounded block — a question with controls, a
 * creative preview, a report. One shared container so they line up.
 */
export function TurnCard({
  children,
  tone = "plain",
  className,
}: {
  children: ReactNode;
  tone?: "plain" | "asking" | "warn";
  className?: string;
}) {
  return (
    <div
      className={cn(
        "mt-3 rounded-xl border p-4 sm:p-5",
        tone === "plain" && "border-line bg-surface",
        tone === "asking" && "border-brand-line bg-brand-soft",
        tone === "warn" && "border-warn-line bg-warn-soft",
        className
      )}
    >
      {children}
    </div>
  );
}

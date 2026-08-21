"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Check,
  ChevronsUpDown,
  ClipboardList,
  CreditCard,
  FolderOpen,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Settings2,
  Sparkles,
  SquarePlus,
} from "lucide-react";
import {
  Dropdown,
  DropdownContent,
  DropdownItem,
  DropdownLabel,
  DropdownSeparator,
  DropdownTrigger,
} from "@/components/ui/dropdown";
import { useApi, useAuth, useOrg } from "@/components/providers";
import { CreditMeter } from "@/components/app/credits";
import { ThemeSwitch } from "@/components/theme";
import type { CreditBalance } from "@/lib/types";
import { cn, formatNumber } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/submissions/new", label: "New review", icon: SquarePlus },
  { href: "/submissions", label: "Submissions", icon: FolderOpen },
  { href: "/reports", label: "Reports", icon: ClipboardList },
  { href: "/billing", label: "Billing & credits", icon: CreditCard },
  { href: "/settings", label: "Settings", icon: Settings2 },
  { href: "/settings/api-keys", label: "API keys", icon: KeyRound, nested: true },
];

export function isNavActive(pathname: string, href: string): boolean {
  if (href === "/submissions")
    return pathname === "/submissions" || pathname.startsWith("/submissions/view");
  if (href === "/settings") return pathname === "/settings";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="App" className="flex flex-col gap-0.5">
      {NAV.map((item) => {
        const active = isNavActive(pathname, item.href);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              // Two cues on the active row, not one: a brand-tinted fill and
              // a left marker. On a dense list the fill alone is easy to lose
              // when scanning, and the marker survives a low-contrast display.
              "relative flex items-center gap-2.5 rounded-xl px-3 py-2 text-[13.5px] font-semibold transition-colors duration-200",
              item.nested && "ml-6",
              active
                ? "bg-brand-soft text-brand-text"
                : "text-subtle hover:bg-tint-2 hover:text-strong"
            )}
          >
            {active && (
              <span
                aria-hidden
                className="absolute top-1/2 -left-px h-4 w-[3px] -translate-y-1/2 rounded-full bg-brand"
              />
            )}
            <Icon
              className={cn("size-4", active ? "text-brand-text" : "text-subtle")}
              aria-hidden
            />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function OrgSwitcher() {
  const { orgs, orgId, orgName, role, selectOrg } = useOrg();
  if (!orgId) return null;
  const multi = orgs.length > 1;
  return (
    <Dropdown>
      <DropdownTrigger
        disabled={!multi}
        className={cn(
          "flex w-full items-center gap-2.5 rounded-xl border border-line bg-surface px-3 py-2.5 text-left shadow-(--shadow-soft)",
          multi && "hover:border-line-strong"
        )}
        aria-label={`Organization: ${orgName ?? "workspace"}${multi ? " — switch" : ""}`}
      >
        <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-[linear-gradient(135deg,var(--brand),var(--indigo-500))] text-[12px] font-extrabold text-brand-on">
          {(orgName ?? "W").slice(0, 1).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] leading-tight font-bold text-strong">
            {orgName}
          </span>
          <span className="block text-[11px] font-semibold text-subtle capitalize">
            {role}
          </span>
        </span>
        {multi && (
          <ChevronsUpDown className="size-3.5 shrink-0 text-subtle" aria-hidden />
        )}
      </DropdownTrigger>
      {multi && (
        <DropdownContent className="w-[248px]">
          <DropdownLabel>Organizations</DropdownLabel>
          {orgs.map((o) => (
            <DropdownItem key={o.org_id} onSelect={() => selectOrg(o.org_id)}>
              <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-tint-2 text-[11px] font-extrabold text-strong">
                {o.name.slice(0, 1).toUpperCase()}
              </span>
              <span className="min-w-0 flex-1 truncate">{o.name}</span>
              {o.org_id === orgId && (
                <Check className="size-4 text-muted" aria-hidden />
              )}
            </DropdownItem>
          ))}
        </DropdownContent>
      )}
    </Dropdown>
  );
}

export const CREDITS_REFRESH_EVENT = "adcoherent:credits-refresh";

export function CreditsWidget() {
  const api = useApi();
  const { orgId } = useOrg();
  const [credits, setCredits] = useState<CreditBalance | null>(null);

  useEffect(() => {
    if (!orgId) return;
    let cancelled = false;
    const load = () =>
      api
        .credits()
        .then((c) => {
          if (!cancelled) setCredits(c);
        })
        .catch(() => {
          /* the pages surface credit errors properly */
        });
    load();
    window.addEventListener(CREDITS_REFRESH_EVENT, load);
    return () => {
      cancelled = true;
      window.removeEventListener(CREDITS_REFRESH_EVENT, load);
    };
  }, [api, orgId]);

  const held = credits?.held ?? 0;

  return (
    <Link
      href="/billing"
      className="card-brand block p-3 transition-colors hover:border-brand-ring"
    >
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-bold tracking-wider text-subtle uppercase">
          Credits
        </p>
        {credits && (
          <span className="rounded-md bg-brand-soft px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-brand-text uppercase">
            {credits.tier}
          </span>
        )}
      </div>
      <p className="mt-1 text-xl font-extrabold text-strong tabular-nums">
        {credits ? formatNumber(credits.total) : "—"}
      </p>
      {credits && <CreditMeter credits={credits} className="mt-2.5" />}
      {/* A balance that drops mid-run is the single most alarming thing this
          widget can show. Naming the escrow inline is what stops it reading
          as money disappearing. */}
      {held > 0 && (
        <p className="mt-2 text-[11px] leading-relaxed text-subtle">
          {formatNumber(held)} reserved by a review in flight — the unused part
          returns when it finishes.
        </p>
      )}
    </Link>
  );
}

export function UserMenu() {
  const { session, signOut } = useAuth();
  const email = session?.user.email ?? "Account";
  return (
    <Dropdown>
      <DropdownTrigger
        className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left hover:bg-tint-2"
        aria-label={`Account menu for ${email}`}
      >
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-[linear-gradient(135deg,var(--indigo-500),var(--cyan-500))] text-[11px] font-extrabold text-white">
          {email.slice(0, 1).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-muted">
          {email}
        </span>
      </DropdownTrigger>
      <DropdownContent className="w-[240px]" align="start">
        <DropdownLabel>Signed in as</DropdownLabel>
        <p className="truncate px-2.5 pb-2 text-[13px] font-semibold text-strong">
          {email}
        </p>
        <DropdownSeparator />
        <DropdownItem
          onSelect={() => {
            void signOut().then(() => window.location.assign("/login"));
          }}
        >
          <LogOut className="size-4 text-subtle" aria-hidden />
          Sign out
        </DropdownItem>
      </DropdownContent>
    </Dropdown>
  );
}

export function SidebarBody({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <>
      <div className="px-1">
        <OrgSwitcher />
      </div>
      <div className="mt-5 flex-1 overflow-y-auto px-1">
        <NavLinks onNavigate={onNavigate} />
      </div>
      <div className="space-y-3 px-1 pt-3">
        <CreditsWidget />
        <div className="rounded-xl border border-line bg-tint p-3">
          <p className="flex items-center gap-1.5 text-[11px] font-bold text-body">
            <Sparkles className="size-3.5 text-accent-text" aria-hidden />
            Decision support
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-subtle">
            Reports inform your compliance process — they are not legal advice.
          </p>
        </div>
        <div className="flex items-center justify-between gap-2 border-t border-line pt-3">
          <span className="text-[11px] font-bold tracking-wider text-subtle uppercase">
            Theme
          </span>
          <ThemeSwitch />
        </div>
        <UserMenu />
      </div>
    </>
  );
}

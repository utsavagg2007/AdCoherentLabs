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
              "flex items-center gap-2.5 rounded-xl px-3 py-2 text-[13.5px] font-semibold transition-colors",
              item.nested && "ml-6",
              active
                ? "bg-violet-50 text-violet-800"
                : "text-zinc-500 hover:bg-zinc-100 hover:text-ink-900"
            )}
          >
            <Icon
              className={cn("size-4", active ? "text-violet-600" : "text-zinc-400")}
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
          "flex w-full items-center gap-2.5 rounded-xl border border-line bg-white px-3 py-2.5 text-left shadow-(--shadow-soft)",
          multi && "hover:border-zinc-300"
        )}
        aria-label={`Organization: ${orgName ?? "workspace"}${multi ? " — switch" : ""}`}
      >
        <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-violet-600 text-[12px] font-extrabold text-white">
          {(orgName ?? "W").slice(0, 1).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] leading-tight font-bold text-ink-900">
            {orgName}
          </span>
          <span className="block text-[11px] font-semibold text-zinc-400 capitalize">
            {role}
          </span>
        </span>
        {multi && (
          <ChevronsUpDown className="size-3.5 shrink-0 text-zinc-400" aria-hidden />
        )}
      </DropdownTrigger>
      {multi && (
        <DropdownContent className="w-[248px]">
          <DropdownLabel>Organizations</DropdownLabel>
          {orgs.map((o) => (
            <DropdownItem key={o.org_id} onSelect={() => selectOrg(o.org_id)}>
              <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-violet-100 text-[11px] font-extrabold text-violet-700">
                {o.name.slice(0, 1).toUpperCase()}
              </span>
              <span className="min-w-0 flex-1 truncate">{o.name}</span>
              {o.org_id === orgId && (
                <Check className="size-4 text-violet-600" aria-hidden />
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

  return (
    <Link
      href="/billing"
      className="block rounded-xl border border-line bg-white p-3 shadow-(--shadow-soft) transition-colors hover:border-violet-200"
    >
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-bold tracking-wider text-zinc-400 uppercase">
          Credits
        </p>
        {credits && (
          <span className="rounded-md bg-violet-50 px-1.5 py-0.5 text-[10px] font-bold tracking-wide text-violet-700 uppercase">
            {credits.tier}
          </span>
        )}
      </div>
      <p className="mt-1 text-xl font-extrabold text-ink-900 tabular-nums">
        {credits ? formatNumber(credits.total) : "—"}
      </p>
      {credits && (
        <p className="mt-0.5 text-[11px] text-zinc-400 tabular-nums">
          {formatNumber(credits.subscription_credits)} plan ·{" "}
          {formatNumber(credits.purchased_credits)} purchased
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
        className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-left hover:bg-zinc-100"
        aria-label={`Account menu for ${email}`}
      >
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-ink-800 text-[11px] font-extrabold text-white">
          {email.slice(0, 1).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-zinc-600">
          {email}
        </span>
      </DropdownTrigger>
      <DropdownContent className="w-[240px]" align="start">
        <DropdownLabel>Signed in as</DropdownLabel>
        <p className="truncate px-2.5 pb-2 text-[13px] font-semibold text-ink-900">
          {email}
        </p>
        <DropdownSeparator />
        <DropdownItem
          onSelect={() => {
            void signOut().then(() => window.location.assign("/login"));
          }}
        >
          <LogOut className="size-4 text-zinc-400" aria-hidden />
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
        <div className="rounded-xl bg-violet-50/70 p-3">
          <p className="flex items-center gap-1.5 text-[11px] font-bold text-violet-800">
            <Sparkles className="size-3.5" aria-hidden />
            Decision support
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-violet-900/60">
            Reports inform your compliance process — they are not legal advice.
          </p>
        </div>
        <UserMenu />
      </div>
    </>
  );
}

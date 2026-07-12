"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CreditCard,
  FileClock,
  Inbox,
  KeyRound,
  LayoutDashboard,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/submissions", label: "Submissions", icon: Inbox },
  { href: "/reports", label: "History & Reports", icon: FileClock },
  { href: "/billing", label: "Billing & Plan", icon: CreditCard },
  { href: "/settings", label: "Settings", icon: Settings, exact: true },
  { href: "/settings/api-keys", label: "API Keys", icon: KeyRound },
] as const;

export function SidebarNav() {
  const pathname = usePathname();
  return (
    <nav className="flex flex-col gap-1">
      {NAV.map((item) => {
        const active =
          "exact" in item && item.exact
            ? pathname === item.href
            : pathname === item.href || pathname.startsWith(item.href + "/");
        return (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors",
              active
                ? "bg-brand/10 text-brand"
                : "text-ink-dim hover:bg-raised hover:text-ink",
            )}
          >
            <item.icon size={15} />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

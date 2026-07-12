import Link from "next/link";
import { LogOut, Plus } from "lucide-react";
import { requireContext } from "@/lib/data";
import { signOut } from "@/app/actions";
import { Logo } from "@/components/logo";
import { SidebarNav } from "@/components/shell/sidebar-nav";
import { OrgSwitcher } from "@/components/shell/org-switcher";
import { QuotaMeter } from "@/components/quota-meter";
import { Badge } from "@/components/ui/badge";
import { buttonClasses } from "@/components/ui/button";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const ctx = await requireContext();

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-line bg-surface/50 p-4 md:flex">
        <Link href="/dashboard" className="px-1 py-2">
          <Logo />
        </Link>

        <div className="mt-4">
          <OrgSwitcher org={ctx.org} orgs={ctx.orgs} />
        </div>

        <Link
          href="/submissions/new"
          className={`${buttonClasses("primary", "sm")} mt-4 w-full`}
        >
          <Plus size={14} /> New submission
        </Link>

        <div className="mt-5 flex-1 overflow-y-auto">
          <SidebarNav />
        </div>

        <div className="space-y-4 border-t border-line pt-4">
          <QuotaMeter quota={ctx.quota} />
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-xs font-medium">{ctx.user.email}</p>
              <p className="text-[10px] uppercase tracking-wider text-ink-faint">
                {ctx.quota.tier} plan
              </p>
            </div>
            <form action={signOut}>
              <button
                type="submit"
                title="Sign out"
                className="grid size-8 place-items-center rounded-lg text-ink-faint transition-colors hover:bg-raised hover:text-ink"
              >
                <LogOut size={14} />
              </button>
            </form>
          </div>
        </div>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col">
        {ctx.demo && (
          <div className="border-b border-brand/20 bg-brand/5 px-5 py-2 text-center">
            <p className="text-[11px] text-brand">
              Demo mode — sample data, writes disabled. Connect Supabase to go
              live (README.md).
            </p>
          </div>
        )}
        {/* Mobile top bar */}
        <header className="flex h-14 items-center justify-between border-b border-line px-4 md:hidden">
          <Link href="/dashboard">
            <Logo />
          </Link>
          <div className="flex items-center gap-2">
            <Badge>{ctx.org.name}</Badge>
            <Link
              href="/submissions/new"
              className={buttonClasses("primary", "sm")}
            >
              <Plus size={14} />
            </Link>
          </div>
        </header>
        <main className="flex-1 px-5 py-8 sm:px-8">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  );
}

"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Menu, X } from "lucide-react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Logo } from "@/components/logo";
import { AppProviders, useAuth, useOrg } from "@/components/providers";
import { SidebarBody } from "@/components/app/sidebar";
import { ToastProvider } from "@/components/ui/toast";
import { PageLoading } from "@/components/ui/feedback";
import { ThemeToggle } from "@/components/theme";

function Shell({ children }: { children: React.ReactNode }) {
  const { session, loading, configured } = useAuth();
  const { orgs, loadingOrgs } = useOrg();
  const router = useRouter();
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => {
    if (loading) return;
    if (!configured || !session) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [loading, configured, session, router, pathname]);

  useEffect(() => {
    if (loading || loadingOrgs || !session) return;
    if (orgs.length === 0) router.replace("/onboarding");
  }, [loading, loadingOrgs, orgs.length, session, router]);

  // `orgs.length === 0` is what makes this a FIRST-LOAD gate rather than a
  // "whenever orgs are being re-read" gate. A background re-discovery (org
  // switch, or a refresh after the session object changes) keeps the current
  // page mounted instead of tearing it down for a full-screen spinner and
  // losing whatever the user had in progress.
  if (loading || !session || (loadingOrgs && orgs.length === 0)) {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-canvas">
        <Logo />
        <PageLoading label="Opening your workspace" />
      </div>
    );
  }

  if (orgs.length === 0) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-canvas">
        <PageLoading label="Checking workspace access" />
      </div>
    );
  }

  return (
    <div className="min-h-dvh bg-canvas">
      {/* mobile top bar */}
      <header className="glass sticky top-0 z-40 flex h-14 items-center justify-between border-b px-4 lg:hidden">
        <Link href="/dashboard" className="rounded-lg">
          <Logo />
        </Link>
        <DialogPrimitive.Root open={drawerOpen} onOpenChange={setDrawerOpen}>
          <div className="flex items-center gap-1">
            <ThemeToggle />
            <DialogPrimitive.Trigger
              aria-label="Open navigation"
              className="flex size-11 cursor-pointer items-center justify-center rounded-full text-strong hover:bg-tint-2"
            >
              <Menu className="size-5" />
            </DialogPrimitive.Trigger>
          </div>
          <DialogPrimitive.Portal>
            <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-[var(--n-975)]/50 backdrop-blur-sm data-[state=open]:animate-fade-in" />
            <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-50 flex w-[min(19rem,85vw)] flex-col border-r border-line bg-raised p-4 shadow-(--shadow-float) focus:outline-none">
              <DialogPrimitive.Title className="sr-only">
                Navigation
              </DialogPrimitive.Title>
              <div className="mb-5 flex items-center justify-between px-1">
                <Logo />
                <DialogPrimitive.Close
                  aria-label="Close navigation"
                  className="rounded-lg p-2 text-subtle hover:bg-tint-2"
                >
                  <X className="size-5" />
                </DialogPrimitive.Close>
              </div>
              <div className="flex min-h-0 flex-1 flex-col">
                <SidebarBody onNavigate={() => setDrawerOpen(false)} />
              </div>
            </DialogPrimitive.Content>
          </DialogPrimitive.Portal>
        </DialogPrimitive.Root>
      </header>

      <div className="lg:grid lg:grid-cols-[248px_1fr]">
        {/* desktop sidebar */}
        <aside className="sticky top-0 hidden h-dvh flex-col border-r border-line bg-sunken px-3 py-5 lg:flex">
          <Link href="/dashboard" className="mb-6 block rounded-lg px-2">
            <Logo />
          </Link>
          <div className="flex min-h-0 flex-1 flex-col">
            <SidebarBody />
          </div>
        </aside>

        <main className="min-w-0 pb-16">{children}</main>
      </div>
    </div>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AppProviders>
      <ToastProvider>
        <Shell>{children}</Shell>
      </ToastProvider>
    </AppProviders>
  );
}

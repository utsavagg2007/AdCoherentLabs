"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Menu, X } from "lucide-react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Logo } from "@/components/logo";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "#how-it-works", label: "How it works" },
  { href: "#live", label: "Live review" },
  { href: "#pricing", label: "Pricing" },
  { href: "#faq", label: "FAQ" },
];

export function MarketingNav() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header
      className={cn(
        "fixed inset-x-0 top-0 z-50 transition-[background-color,border-color,box-shadow] duration-300",
        scrolled
          ? "glass-dark border-b border-white/8 shadow-(--shadow-soft)"
          : "bg-transparent"
      )}
    >
      <div className="container-wide flex h-16 items-center justify-between gap-4">
        <Link href="/" aria-label="AdCoherent Labs home" className="rounded-lg">
          <Logo />
        </Link>

        <nav aria-label="Main" className="hidden items-center gap-1 md:flex">
          {LINKS.map((l) => (
            <a
              key={l.href}
              href={l.href}
              className="rounded-full px-3.5 py-2 text-sm font-semibold text-ink-600 transition-colors duration-200 hover:bg-white/8 hover:text-ink-900"
            >
              {l.label}
            </a>
          ))}
        </nav>

        <div className="hidden items-center gap-2.5 md:flex">
          <Link
            href="/login"
            className="rounded-full px-3.5 py-2 text-sm font-semibold text-ink-600 transition-colors duration-200 hover:text-ink-900"
          >
            Sign in
          </Link>
          <Link href="/signup" className="btn-primary sheen !py-2 text-[13px]">
            Run a compliance check
          </Link>
        </div>

        {/* mobile drawer */}
        <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
          <DialogPrimitive.Trigger
            aria-label="Open menu"
            className="rounded-lg p-2 text-ink-900 md:hidden"
          >
            <Menu className="size-5" />
          </DialogPrimitive.Trigger>
          <DialogPrimitive.Portal>
            <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-coal-950/70 backdrop-blur-sm data-[state=open]:animate-fade-in md:hidden" />
            <DialogPrimitive.Content className="fixed inset-y-0 right-0 z-50 flex w-[min(20rem,85vw)] flex-col border-l border-white/10 bg-coal-850 p-6 shadow-2xl focus:outline-none md:hidden">
              <DialogPrimitive.Title className="sr-only">
                Navigation menu
              </DialogPrimitive.Title>
              <div className="flex items-center justify-between">
                <Logo />
                <DialogPrimitive.Close
                  aria-label="Close menu"
                  className="rounded-lg p-2 text-ink-600 hover:bg-white/10 hover:text-ink-900"
                >
                  <X className="size-5" />
                </DialogPrimitive.Close>
              </div>
              <nav aria-label="Mobile" className="mt-8 flex flex-col gap-1">
                {LINKS.map((l) => (
                  <a
                    key={l.href}
                    href={l.href}
                    onClick={() => setOpen(false)}
                    className="rounded-xl px-3 py-3 text-[15px] font-semibold text-ink-700 hover:bg-white/10 hover:text-ink-900"
                  >
                    {l.label}
                  </a>
                ))}
              </nav>
              <div className="mt-auto flex flex-col gap-3">
                <Link
                  href="/login"
                  onClick={() => setOpen(false)}
                  className="btn-ghost-dark w-full"
                >
                  Sign in
                </Link>
                <Link
                  href="/signup"
                  onClick={() => setOpen(false)}
                  className="btn-primary w-full"
                >
                  Run a compliance check
                </Link>
              </div>
            </DialogPrimitive.Content>
          </DialogPrimitive.Portal>
        </DialogPrimitive.Root>
      </div>
    </header>
  );
}

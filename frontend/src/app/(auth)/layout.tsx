import Link from "next/link";
import Image from "next/image";
import { Logo } from "@/components/logo";
import { ThemeToggle } from "@/components/theme";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1fr_1.1fr]">
      {/* Brand panel. The artwork is a deep-indigo render, so this column
          stays dark in both themes and its copy is pinned to light tones
          rather than following the theme tokens. */}
      <aside className="relative hidden overflow-hidden bg-[var(--n-975)] lg:block">
        <Image
          src="/media/auth-panel.png"
          alt=""
          fill
          sizes="(min-width: 1024px) 48vw, 0px"
          className="object-cover opacity-90"
          aria-hidden
          priority
        />
        <div className="absolute inset-0 bg-[linear-gradient(to_top,rgb(7_7_14/0.92),rgb(7_7_14/0.35)_45%,rgb(7_7_14/0.6))]" />
        <div className="relative flex h-full flex-col justify-between p-10">
          <Link href="/" className="w-fit rounded-lg">
            <Logo tone="light" />
          </Link>
          <div className="max-w-md">
            <p className="font-display text-2xl leading-snug font-bold tracking-tight text-white text-balance">
              Every finding, with its evidence, citation, and a way to fix it.
            </p>
            <p className="mt-4 text-[13px] leading-relaxed text-white/60">
              AI-assisted compliance review for US fintech advertising.
              Decision support, not legal advice.
            </p>
          </div>
        </div>
      </aside>

      {/* form panel */}
      <div className="bg-wash flex flex-col bg-canvas">
        <div className="flex items-center justify-between p-6 lg:p-6">
          <Link href="/" className="rounded-lg lg:invisible">
            <Logo />
          </Link>
          <ThemeToggle />
        </div>
        <div className="flex flex-1 items-center justify-center px-5 pb-10 sm:px-10">
          <div className="w-full max-w-sm">{children}</div>
        </div>
        <p className="p-6 text-center text-[12px] text-subtle">
          Decision support, not legal advice.
        </p>
      </div>
    </div>
  );
}

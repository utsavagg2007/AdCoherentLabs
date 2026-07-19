import Link from "next/link";
import { Logo } from "@/components/logo";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1fr_1.1fr]">
      {/* brand panel */}
      <aside
        data-surface="dark"
        className="relative hidden overflow-hidden bg-ink-950 lg:block"
        aria-hidden
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src="/videos/hero-still.jpg"
          alt=""
          className="absolute inset-0 size-full object-cover opacity-60"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-ink-950 via-ink-950/40 to-ink-950/70" />
        <div className="relative flex h-full flex-col justify-between p-10">
          <Link href="/" className="w-fit rounded-lg">
            <Logo tone="light" />
          </Link>
          <div className="max-w-md">
            <p className="text-2xl leading-snug font-bold tracking-tight text-white/90 text-balance">
              Every finding, with its evidence, citation, and a way to fix it.
            </p>
            <p className="mt-4 text-[13px] leading-relaxed text-white/45">
              AI-assisted compliance review for US fintech advertising.
              Decision support, not legal advice.
            </p>
          </div>
        </div>
      </aside>

      {/* form panel */}
      <div className="flex flex-col bg-paper">
        <div className="flex items-center justify-between p-6 lg:hidden">
          <Link href="/" className="rounded-lg">
            <Logo tone="dark" />
          </Link>
        </div>
        <div className="flex flex-1 items-center justify-center px-5 py-10 sm:px-10">
          <div className="w-full max-w-sm">{children}</div>
        </div>
        <p className="p-6 text-center text-[12px] text-zinc-400">
          Decision support, not legal advice.
        </p>
      </div>
    </div>
  );
}

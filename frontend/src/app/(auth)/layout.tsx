import Link from "next/link";
import Image from "next/image";
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
        className="relative hidden overflow-hidden bg-coal-950 lg:block"
        aria-hidden
      >
        <Image
          src="/media/hero-still.jpg"
          alt=""
          fill
          sizes="50vw"
          className="object-cover opacity-70"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-coal-950 via-coal-950/35 to-coal-950/70" />
        <div className="relative flex h-full flex-col justify-between p-10">
          <Link href="/" className="w-fit rounded-lg">
            <Logo />
          </Link>
          <div className="max-w-md">
            <p className="text-chrome font-display text-2xl leading-snug font-bold tracking-tight text-balance">
              Every finding, with its evidence, citation, and a way to fix it.
            </p>
            <p className="mt-4 text-[13px] leading-relaxed text-ink-500">
              AI-assisted compliance review for US fintech advertising.
              Decision support, not legal advice.
            </p>
          </div>
        </div>
      </aside>

      {/* form panel */}
      <div className="flex flex-col bg-coal-900">
        <div className="flex items-center justify-between p-6 lg:hidden">
          <Link href="/" className="rounded-lg">
            <Logo />
          </Link>
        </div>
        <div className="flex flex-1 items-center justify-center px-5 py-10 sm:px-10">
          <div className="w-full max-w-sm">{children}</div>
        </div>
        <p className="p-6 text-center text-[12px] text-ink-500">
          Decision support, not legal advice.
        </p>
      </div>
    </div>
  );
}

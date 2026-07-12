import Link from "next/link";
import { Logo } from "@/components/logo";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center px-5 py-12">
      <div className="bg-grid absolute inset-0 [mask-image:radial-gradient(50%_50%_at_50%_40%,black,transparent)]" />
      <div className="relative w-full max-w-sm">
        <Link href="/" className="mb-8 flex justify-center">
          <Logo />
        </Link>
        <div className="rounded-2xl border border-line bg-surface p-7 shadow-2xl shadow-black/40">
          {children}
        </div>
        <p className="mt-6 text-center text-[11px] text-ink-faint">
          Multi-tenant, RLS-isolated, audit-logged. Decision support — not legal
          advice.
        </p>
      </div>
    </div>
  );
}

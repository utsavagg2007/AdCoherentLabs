import Link from "next/link";
import { Logo } from "@/components/logo";
import { buttonClasses } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-5 text-center">
      <Logo />
      <div>
        <p className="font-mono text-5xl font-semibold text-brand">404</p>
        <p className="mt-3 text-sm text-ink-dim">
          That page doesn&apos;t exist — or belongs to another tenant, in which
          case RLS is doing its job.
        </p>
      </div>
      <Link href="/dashboard" className={buttonClasses("secondary", "sm")}>
        Back to dashboard
      </Link>
    </div>
  );
}

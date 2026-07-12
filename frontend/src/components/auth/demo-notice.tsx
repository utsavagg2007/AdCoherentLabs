import Link from "next/link";
import { buttonClasses } from "@/components/ui/button";

/** Shown on auth pages when no Supabase backend is configured. */
export function DemoNotice() {
  return (
    <div className="space-y-4 rounded-xl border border-brand/25 bg-brand/5 p-4 text-center">
      <p className="text-xs leading-relaxed text-ink-dim">
        <span className="font-semibold text-brand">Demo mode.</span> No Supabase
        backend is configured, so sign-in is disabled — but the whole product is
        browsable with sample data.
      </p>
      <Link href="/dashboard" className={buttonClasses("primary", "sm")}>
        Explore the demo
      </Link>
      <p className="text-[11px] text-ink-faint">
        To go live, set the Supabase env vars — see README.md.
      </p>
    </div>
  );
}

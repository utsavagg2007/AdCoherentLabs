"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { isDemoMode } from "@/lib/env";
import { Button } from "@/components/ui/button";
import { MailCheck } from "lucide-react";

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmail />
    </Suspense>
  );
}

function VerifyEmail() {
  const params = useSearchParams();
  const email = params.get("email") ?? "";
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function resend() {
    if (!email || isDemoMode) return;
    const supabase = createClient();
    const { error } = await supabase.auth.resend({
      type: "signup",
      email,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback?next=/onboarding`,
      },
    });
    if (error) setError(error.message);
    else setSent(true);
  }

  return (
    <div className="space-y-5 text-center">
      <span className="mx-auto grid size-12 place-items-center rounded-full bg-brand/10 text-brand">
        <MailCheck size={22} />
      </span>
      <div>
        <h1 className="text-lg font-semibold tracking-tight">
          Check your inbox
        </h1>
        <p className="mt-2 text-xs leading-relaxed text-ink-dim">
          We sent a confirmation link{email ? ` to ${email}` : ""}. Email
          verification is required before you can run analyses.
        </p>
      </div>
      {error && (
        <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      )}
      {sent ? (
        <p className="text-xs text-brand">Sent — give it a minute.</p>
      ) : (
        <Button variant="secondary" size="sm" onClick={resend} disabled={!email}>
          Resend the email
        </Button>
      )}
      <p className="text-xs text-ink-dim">
        Wrong address?{" "}
        <Link href="/signup" className="font-medium text-brand hover:underline">
          Sign up again
        </Link>
      </p>
    </div>
  );
}

"use client";

import { useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { isDemoMode } from "@/lib/env";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { DemoNotice } from "@/components/auth/demo-notice";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  if (isDemoMode) {
    return (
      <div className="space-y-5">
        <Heading />
        <DemoNotice />
      </div>
    );
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    const supabase = createClient();
    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/auth/callback?next=/reset-password`,
    });
    setPending(false);
    if (error) setError(error.message);
    else setSent(true);
  }

  return (
    <div className="space-y-5">
      <Heading />
      {sent ? (
        <p className="rounded-lg border border-brand/30 bg-brand/10 px-3 py-3 text-center text-xs text-brand">
          If an account exists for {email}, a reset link is on its way.
        </p>
      ) : (
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="email">Work email</Label>
            <Input
              id="email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          {error && (
            <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={pending}>
            {pending ? "Sending…" : "Send reset link"}
          </Button>
        </form>
      )}
      <p className="text-center text-xs text-ink-dim">
        <Link href="/login" className="font-medium text-brand hover:underline">
          Back to sign in
        </Link>
      </p>
    </div>
  );
}

function Heading() {
  return (
    <div className="text-center">
      <h1 className="text-lg font-semibold tracking-tight">Reset password</h1>
      <p className="mt-1 text-xs text-ink-dim">
        We&apos;ll email you a secure reset link.
      </p>
    </div>
  );
}

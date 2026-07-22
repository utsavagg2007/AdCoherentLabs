"use client";

import Link from "next/link";
import { useState } from "react";
import { MailCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const configured = supabaseConfigured();

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!configured) return;
    setBusy(true);
    setError(null);
    const { error } = await getSupabase().auth.resetPasswordForEmail(
      email.trim(),
      { redirectTo: `${window.location.origin}/reset-password` }
    );
    setBusy(false);
    if (error) {
      setError(error.message);
      return;
    }
    setDone(true);
  }

  if (done) {
    return (
      <div className="text-center">
        <div className="mx-auto flex size-14 items-center justify-center rounded-2xl border border-white/15 bg-white/6 text-ink-600">
          <MailCheck className="size-6" aria-hidden />
        </div>
        <h1 className="mt-5 text-2xl font-extrabold tracking-tight text-ink-900">
          Check your email
        </h1>
        <p className="mx-auto mt-2 max-w-xs text-sm leading-relaxed text-ink-500">
          If an account exists for{" "}
          <span className="font-semibold text-ink-800">{email}</span>, a reset
          link is on its way.
        </p>
        <Button href="/login" variant="secondary" className="mt-7">
          Back to sign in
        </Button>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-extrabold tracking-tight text-ink-900">
        Reset your password
      </h1>
      <p className="mt-1.5 text-sm text-ink-500">
        Enter your email and we&apos;ll send a reset link.
      </p>
      <form onSubmit={onSubmit} className="mt-7 space-y-4" noValidate>
        <div>
          <label htmlFor="email" className="label">
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            required
            className="input"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com"
          />
        </div>
        {error && (
          <div role="alert" className="rounded-xl border border-red-400/25 bg-red-400/10 p-3.5 text-[13px] text-red-300">
            {error}
          </div>
        )}
        <Button
          type="submit"
          className="w-full"
          size="lg"
          loading={busy}
          disabled={!configured || !email}
        >
          Send reset link
        </Button>
      </form>
      <p className="mt-6 text-center text-[13.5px] text-ink-500">
        Remembered it?{" "}
        <Link href="/login" className="font-bold text-ink-900 hover:text-white">
          Sign in
        </Link>
      </p>
    </div>
  );
}

"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next") || "/dashboard";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const [resent, setResent] = useState(false);
  const configured = supabaseConfigured();

  useEffect(() => {
    if (!configured) return;
    getSupabase()
      .auth.getSession()
      .then(({ data }) => {
        if (data.session) router.replace(next);
      });
  }, [configured, router, next]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!configured) return;
    setBusy(true);
    setError(null);
    setUnconfirmed(false);
    const { error } = await getSupabase().auth.signInWithPassword({
      email: email.trim(),
      password,
    });
    setBusy(false);
    if (error) {
      const msg = error.message.toLowerCase();
      if (msg.includes("confirm")) {
        setUnconfirmed(true);
        setError("Confirm your email before signing in.");
      } else if (msg.includes("invalid")) {
        setError("That email and password combination doesn't match.");
      } else {
        setError(error.message);
      }
      return;
    }
    router.replace(next);
  }

  async function resendConfirmation() {
    if (!configured || !email) return;
    await getSupabase().auth.resend({ type: "signup", email: email.trim() });
    setResent(true);
  }

  return (
    <div>
      <h1 className="text-2xl font-extrabold tracking-tight text-ink-900">
        Welcome back
      </h1>
      <p className="mt-1.5 text-sm text-ink-500">
        Sign in to your review workspace.
      </p>

      {!configured && (
        <div role="alert" className="mt-6 rounded-xl border border-amber-400/25 bg-amber-400/10 p-3.5 text-[13px] leading-relaxed text-amber-200">
          Authentication isn&apos;t configured. Set{" "}
          <code className="font-mono text-[12px]">NEXT_PUBLIC_SUPABASE_URL</code>{" "}
          and{" "}
          <code className="font-mono text-[12px]">
            NEXT_PUBLIC_SUPABASE_ANON_KEY
          </code>
          , then restart the dev server.
        </div>
      )}

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
        <div>
          <div className="flex items-baseline justify-between">
            <label htmlFor="password" className="label">
              Password
            </label>
            <Link
              href="/forgot-password"
              className="text-[12.5px] font-semibold text-ink-900 hover:text-white"
            >
              Forgot password?
            </Link>
          </div>
          <div className="relative">
            <input
              id="password"
              type={showPw ? "text" : "password"}
              autoComplete="current-password"
              required
              className="input pr-11"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••••"
            />
            <button
              type="button"
              onClick={() => setShowPw((s) => !s)}
              aria-label={showPw ? "Hide password" : "Show password"}
              className="absolute top-1/2 right-3 -translate-y-1/2 rounded-md p-1 text-ink-500 hover:text-ink-800"
            >
              {showPw ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
        </div>

        {error && (
          <div role="alert" className="rounded-xl border border-red-400/25 bg-red-400/10 p-3.5 text-[13px] leading-relaxed text-red-300">
            {error}
            {unconfirmed && (
              <button
                type="button"
                onClick={resendConfirmation}
                className="mt-1.5 block font-bold text-red-200 underline underline-offset-2"
              >
                {resent ? "Confirmation email sent ✓" : "Resend confirmation email"}
              </button>
            )}
          </div>
        )}

        <Button
          type="submit"
          className="w-full"
          size="lg"
          loading={busy}
          disabled={!configured || !email || !password}
        >
          Sign in
        </Button>
      </form>

      <p className="mt-6 text-center text-[13.5px] text-ink-500">
        New to AdCoherent?{" "}
        <Link
          href="/signup"
          className="font-bold text-ink-900 hover:text-white"
        >
          Create an account
        </Link>
      </p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}

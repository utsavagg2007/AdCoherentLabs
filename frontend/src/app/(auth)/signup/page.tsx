"use client";

import Link from "next/link";
import { useState } from "react";
import { Eye, EyeOff, MailCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";
import { AuthDivider, OAuthButtons } from "@/components/auth/oauth-buttons";

export default function SignupPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const configured = supabaseConfigured();

  const pwTooShort = password.length > 0 && password.length < 8;
  const mismatch = confirm.length > 0 && confirm !== password;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!configured || pwTooShort || password !== confirm) return;
    setBusy(true);
    setError(null);
    const { data, error } = await getSupabase().auth.signUp({
      email: email.trim(),
      password,
      options: {
        emailRedirectTo:
          typeof window !== "undefined"
            ? `${window.location.origin}/login`
            : undefined,
      },
    });
    setBusy(false);
    if (error) {
      setError(error.message);
      return;
    }
    // Supabase returns an obfuscated user for existing addresses — the copy
    // stays neutral so account existence is never revealed.
    if (data.user && !data.session) {
      setDone(true);
    } else if (data.session) {
      window.location.assign("/onboarding");
    } else {
      setDone(true);
    }
  }

  if (done) {
    return (
      <div className="text-center">
        <div className="mx-auto flex size-14 items-center justify-center rounded-2xl border border-line-strong bg-tint text-muted">
          <MailCheck className="size-6" aria-hidden />
        </div>
        <h1 className="mt-5 text-2xl font-extrabold tracking-tight text-strong">
          Check your email
        </h1>
        <p className="mx-auto mt-2 max-w-xs text-sm leading-relaxed text-subtle">
          If an account can be created for{" "}
          <span className="font-semibold text-body">{email}</span>, a
          confirmation link is on its way. Confirm it, then sign in.
        </p>
        <Button href="/login" variant="secondary" className="mt-7">
          Back to sign in
        </Button>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-extrabold tracking-tight text-strong">
        Create your account
      </h1>
      <p className="mt-1.5 text-sm text-subtle">
        Start on the Free plan — 25 credits monthly, no card required.
      </p>

      {!configured && (
        <div role="alert" className="mt-6 rounded-xl border border-warn-line bg-warn-soft p-3.5 text-[13px] leading-relaxed text-warn">
          Authentication isn&apos;t configured. Set the Supabase environment
          variables, then restart the dev server.
        </div>
      )}

      {/* A social sign-up skips email confirmation entirely — the provider
          has already verified the address — so it is the path most people
          should take, and it leads. */}
      <OAuthButtons verb="Sign up with" className="mt-7" />
      <AuthDivider label="or use email" />

      <form onSubmit={onSubmit} className="space-y-4" noValidate>
        <div>
          <label htmlFor="email" className="label">
            Work email
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
          <label htmlFor="password" className="label">
            Password
          </label>
          <div className="relative">
            <input
              id="password"
              type={showPw ? "text" : "password"}
              autoComplete="new-password"
              required
              minLength={8}
              className="input pr-11"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
              aria-describedby="pw-hint"
            />
            <button
              type="button"
              onClick={() => setShowPw((s) => !s)}
              aria-label={showPw ? "Hide password" : "Show password"}
              className="absolute top-1/2 right-3 -translate-y-1/2 rounded-md p-1 text-subtle hover:text-body"
            >
              {showPw ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </div>
          {pwTooShort && (
            <p id="pw-hint" className="mt-1.5 text-[12.5px] text-fail">
              Use at least 8 characters.
            </p>
          )}
        </div>
        <div>
          <label htmlFor="confirm" className="label">
            Confirm password
          </label>
          <input
            id="confirm"
            type={showPw ? "text" : "password"}
            autoComplete="new-password"
            required
            className="input"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="Repeat your password"
          />
          {mismatch && (
            <p className="mt-1.5 text-[12.5px] text-fail">
              Passwords don&apos;t match.
            </p>
          )}
        </div>

        {error && (
          <div role="alert" className="rounded-xl border border-fail-line bg-fail-soft p-3.5 text-[13px] leading-relaxed text-fail">
            {error}
          </div>
        )}

        <Button
          type="submit"
          className="w-full"
          size="lg"
          loading={busy}
          disabled={
            !configured || !email || !password || pwTooShort || password !== confirm
          }
        >
          Create account
        </Button>
      </form>

      <p className="mt-6 text-center text-[13.5px] text-subtle">
        Already have an account?{" "}
        <Link
          href="/login"
          className="font-bold text-strong hover:text-brand-text"
        >
          Sign in
        </Link>
      </p>
    </div>
  );
}

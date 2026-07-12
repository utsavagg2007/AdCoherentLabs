"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { isDemoMode } from "@/lib/env";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { DemoNotice } from "@/components/auth/demo-notice";
import { Code2, Mail, Sparkles } from "lucide-react";

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const rawNext = params.get("next");
  // Same-origin relative paths only — never an open redirect.
  const next =
    rawNext && rawNext.startsWith("/") && !rawNext.startsWith("//")
      ? rawNext
      : "/dashboard";

  const [mode, setMode] = useState<"password" | "magic">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(
    params.get("error"),
  );
  const [notice, setNotice] = useState<string | null>(null);

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
    setNotice(null);
    const supabase = createClient();

    if (mode === "password") {
      const { error } = await supabase.auth.signInWithPassword({
        email,
        password,
      });
      if (error) {
        setError(
          error.message === "Email not confirmed"
            ? "Verify your email first — check your inbox for the confirmation link."
            : error.message,
        );
        setPending(false);
        return;
      }
      router.push(next);
      router.refresh();
    } else {
      const { error } = await supabase.auth.signInWithOtp({
        email,
        options: {
          emailRedirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`,
        },
      });
      setPending(false);
      if (error) setError(error.message);
      else setNotice("Magic link sent — check your inbox.");
    }
  }

  async function oauth(provider: "google" | "github") {
    const supabase = createClient();
    await supabase.auth.signInWithOAuth({
      provider,
      options: {
        redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`,
      },
    });
  }

  return (
    <div className="space-y-5">
      <Heading />

      <div className="grid grid-cols-2 gap-2">
        <Button variant="secondary" size="sm" onClick={() => oauth("google")}>
          <Mail size={14} /> Google
        </Button>
        <Button variant="secondary" size="sm" onClick={() => oauth("github")}>
          <Code2 size={14} /> GitHub
        </Button>
      </div>

      <div className="flex items-center gap-3 text-[11px] text-ink-faint">
        <span className="h-px flex-1 bg-line" />
        or with email
        <span className="h-px flex-1 bg-line" />
      </div>

      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="email">Work email</Label>
          <Input
            id="email"
            type="email"
            required
            autoComplete="email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>

        {mode === "password" && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="password">Password</Label>
              <Link
                href="/forgot-password"
                className="text-[11px] text-ink-faint hover:text-ink"
              >
                Forgot?
              </Link>
            </div>
            <Input
              id="password"
              type="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
        )}

        {error && (
          <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        )}
        {notice && (
          <p className="rounded-lg border border-brand/30 bg-brand/10 px-3 py-2 text-xs text-brand">
            {notice}
          </p>
        )}

        <Button type="submit" className="w-full" disabled={pending}>
          {pending
            ? "Signing in…"
            : mode === "password"
              ? "Sign in"
              : "Send magic link"}
        </Button>
      </form>

      <button
        type="button"
        onClick={() => setMode(mode === "password" ? "magic" : "password")}
        className="flex w-full items-center justify-center gap-1.5 text-[11px] text-ink-faint hover:text-ink"
      >
        <Sparkles size={12} />
        {mode === "password"
          ? "Use a magic link instead"
          : "Use a password instead"}
      </button>

      <p className="text-center text-xs text-ink-dim">
        New here?{" "}
        <Link href="/signup" className="font-medium text-brand hover:underline">
          Create an account
        </Link>
      </p>
    </div>
  );
}

function Heading() {
  return (
    <div className="text-center">
      <h1 className="text-lg font-semibold tracking-tight">Welcome back</h1>
      <p className="mt-1 text-xs text-ink-dim">
        Sign in to review your compliance runs.
      </p>
    </div>
  );
}

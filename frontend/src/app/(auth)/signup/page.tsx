"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { isDemoMode } from "@/lib/env";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import { DemoNotice } from "@/components/auth/demo-notice";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback?next=/onboarding`,
      },
    });
    if (error) {
      setError(error.message);
      setPending(false);
      return;
    }
    // Email verification is required before analysis features (Phase 3).
    if (data.user && !data.session) {
      router.push(`/verify-email?email=${encodeURIComponent(email)}`);
    } else {
      router.push("/onboarding");
      router.refresh();
    }
  }

  return (
    <div className="space-y-5">
      <Heading />
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
          <p className="text-[11px] text-ink-faint">
            Use your business domain — teams are organized by company.
          </p>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            placeholder="8+ characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        {error && (
          <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {error}
          </p>
        )}

        <Button type="submit" className="w-full" disabled={pending}>
          {pending ? "Creating account…" : "Create account"}
        </Button>
      </form>
      <p className="text-center text-xs text-ink-dim">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-brand hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}

function Heading() {
  return (
    <div className="text-center">
      <h1 className="text-lg font-semibold tracking-tight">
        Create your account
      </h1>
      <p className="mt-1 text-xs text-ink-dim">
        Free tier: 20 scans a month, no card required.
      </p>
    </div>
  );
}

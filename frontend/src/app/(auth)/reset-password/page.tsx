"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";

/** Users land here from the recovery email — Supabase establishes a
 * recovery session from the link before the new password can be set. */
export default function ResetPasswordPage() {
  const router = useRouter();
  const configuredAtMount = supabaseConfigured();
  const [hasSession, setHasSession] = useState<boolean | null>(
    configuredAtMount ? null : false
  );
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const configured = supabaseConfigured();

  useEffect(() => {
    if (!configured) return;
    const supabase = getSupabase();
    supabase.auth.getSession().then(({ data }) => {
      setHasSession(Boolean(data.session));
    });
    const { data: sub } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === "PASSWORD_RECOVERY" || session) setHasSession(true);
    });
    return () => sub.subscription.unsubscribe();
  }, [configured]);

  const pwTooShort = password.length > 0 && password.length < 8;
  const mismatch = confirm.length > 0 && confirm !== password;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (pwTooShort || password !== confirm) return;
    setBusy(true);
    setError(null);
    const { error } = await getSupabase().auth.updateUser({ password });
    setBusy(false);
    if (error) {
      setError(error.message);
      return;
    }
    setDone(true);
    setTimeout(() => router.replace("/dashboard"), 1600);
  }

  if (hasSession === null) {
    return <p className="text-center text-sm text-ink-500">Checking your reset link…</p>;
  }

  if (!hasSession) {
    return (
      <div className="text-center">
        <div className="mx-auto flex size-14 items-center justify-center rounded-2xl border border-amber-400/25 bg-amber-400/10 text-amber-300">
          <KeyRound className="size-6" aria-hidden />
        </div>
        <h1 className="mt-5 text-2xl font-extrabold tracking-tight text-ink-900">
          Reset link needed
        </h1>
        <p className="mx-auto mt-2 max-w-xs text-sm leading-relaxed text-ink-500">
          This page only works from the link in a password-reset email, and
          links expire quickly. Request a fresh one.
        </p>
        <Button href="/forgot-password" className="mt-7">
          Request reset link
        </Button>
      </div>
    );
  }

  if (done) {
    return (
      <div className="text-center">
        <h1 className="text-2xl font-extrabold tracking-tight text-ink-900">
          Password updated
        </h1>
        <p className="mt-2 text-sm text-ink-500">Taking you to your dashboard…</p>
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-extrabold tracking-tight text-ink-900">
        Choose a new password
      </h1>
      <form onSubmit={onSubmit} className="mt-7 space-y-4" noValidate>
        <div>
          <label htmlFor="password" className="label">
            New password
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
          {pwTooShort && (
            <p className="mt-1.5 text-[12.5px] text-red-300">
              Use at least 8 characters.
            </p>
          )}
        </div>
        <div>
          <label htmlFor="confirm" className="label">
            Confirm new password
          </label>
          <input
            id="confirm"
            type={showPw ? "text" : "password"}
            autoComplete="new-password"
            required
            className="input"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
          {mismatch && (
            <p className="mt-1.5 text-[12.5px] text-red-300">
              Passwords don&apos;t match.
            </p>
          )}
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
          disabled={!password || pwTooShort || password !== confirm}
        >
          Update password
        </Button>
      </form>
    </div>
  );
}

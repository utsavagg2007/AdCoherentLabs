"use client";

/** OAuth return trip.
 *
 * Supabase sends the browser here with `?code=…` (PKCE) after the provider
 * approves. The client is configured with `detectSessionInUrl`, so it
 * performs the exchange itself the moment it loads — this page's job is to
 * wait for that to land and then route onward, rather than letting the app
 * shell see a session-less first render and bounce the user back to /login.
 *
 * It deliberately does NOT decide whether the user needs onboarding. The app
 * layout already owns that (zero memberships → /onboarding) and one owner is
 * better than two that can disagree. */

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ShieldAlert } from "lucide-react";
import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { PageLoading } from "@/components/ui/feedback";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";

/** How long to wait for the client to exchange the code before giving up.
 * Generous: this covers a cold network, not a fast failure. */
const EXCHANGE_TIMEOUT_MS = 15_000;

function CallbackHandler() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  // Only same-origin paths are honoured — an attacker-supplied `next` would
  // otherwise turn this route into an open redirect.
  const raw = params.get("next");
  const next = raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/dashboard";

  const providerError = params.get("error_description") || params.get("error");

  const finish = useCallback(() => {
    // replace, not push: the callback URL still carries the auth code and
    // must not be reachable with the back button.
    router.replace(next);
  }, [router, next]);

  useEffect(() => {
    if (providerError || !supabaseConfigured()) return;

    const supabase = getSupabase();
    let done = false;

    const settle = (session: unknown) => {
      if (done || !session) return;
      done = true;
      finish();
    };

    // The exchange may complete before or after this effect runs, so watch
    // both paths: the event, and the session that may already be there.
    const { data: sub } = supabase.auth.onAuthStateChange((_e, session) =>
      settle(session)
    );
    supabase.auth.getSession().then(({ data }) => settle(data.session));

    const timer = setTimeout(() => {
      if (done) return;
      done = true;
      setError(
        "That sign-in link expired or was already used. Start again from the sign-in page."
      );
    }, EXCHANGE_TIMEOUT_MS);

    return () => {
      sub.subscription.unsubscribe();
      clearTimeout(timer);
    };
  }, [providerError, finish]);

  const message = providerError
    ? // Providers phrase a user-cancelled consent screen a dozen ways; the
      // only one worth its own copy is the deliberate refusal.
      /denied|cancel/i.test(providerError)
      ? "You cancelled the sign-in before approving access."
      : providerError
    : error;

  if (message) {
    return (
      <div className="w-full max-w-sm text-center">
        <div className="mx-auto flex size-14 items-center justify-center rounded-2xl border border-fail-line bg-fail-soft text-fail">
          <ShieldAlert className="size-6" aria-hidden />
        </div>
        <h1 className="mt-5 text-2xl font-extrabold tracking-tight text-strong">
          Sign-in didn&apos;t complete
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-subtle">{message}</p>
        <div className="mt-6 flex flex-col gap-2.5">
          <Button href="/login" className="w-full" size="lg">
            Back to sign in
          </Button>
          <Link
            href="/signup"
            className="text-[13.5px] font-semibold text-subtle hover:text-brand-text"
          >
            Create an account instead
          </Link>
        </div>
      </div>
    );
  }

  return <PageLoading label="Completing sign-in" />;
}

export default function OAuthCallbackPage() {
  return (
    <div className="bg-wash flex min-h-dvh flex-col items-center justify-center gap-8 bg-canvas px-5">
      <Logo />
      <Suspense fallback={<PageLoading label="Completing sign-in" />}>
        <CallbackHandler />
      </Suspense>
    </div>
  );
}

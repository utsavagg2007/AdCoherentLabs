"use client";

/** Social sign-in, shared by /login and /signup.
 *
 * OAuth makes no distinction between the two — the provider returns an
 * identity, and GoTrue either matches an existing user or creates one. So
 * this is a single component and the surrounding copy is what differs. */

import { useState } from "react";
import { Loader2 } from "lucide-react";
import type { Provider } from "@supabase/supabase-js";
import { enabledProviders, oauthRedirectUrl } from "@/lib/oauth";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";
import { cn } from "@/lib/utils";
import { ProviderMark } from "./provider-marks";

export function OAuthButtons({
  next,
  /** Verb for the button label — "Sign in with" or "Sign up with". */
  verb = "Continue with",
  className,
}: {
  next?: string | null;
  verb?: string;
  className?: string;
}) {
  const providers = enabledProviders();
  const configured = supabaseConfigured();
  const [pending, setPending] = useState<Provider | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!configured || providers.length === 0) return null;

  async function start(provider: Provider) {
    setPending(provider);
    setError(null);
    const { error } = await getSupabase().auth.signInWithOAuth({
      provider,
      options: {
        redirectTo: oauthRedirectUrl(next),
        scopes: providers.find((p) => p.id === provider)?.scopes,
      },
    });
    // On success the browser has already been handed to the provider and
    // this code never runs. Reaching here at all means the redirect was
    // refused — almost always the provider is not enabled in Supabase.
    if (error) {
      setPending(null);
      setError(
        /provider is not enabled/i.test(error.message)
          ? "That sign-in method isn't enabled for this workspace yet."
          : error.message
      );
    }
  }

  return (
    <div className={className}>
      <div className="grid gap-2.5">
        {providers.map((p) => {
          const busy = pending === p.id;
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => start(p.id)}
              disabled={pending !== null}
              className={cn(
                // Neutral chrome, brand mark. Matches btn-secondary so the
                // violet CTA below stays the single strongest thing here.
                "flex h-11 w-full cursor-pointer items-center justify-center gap-2.5",
                "rounded-full border border-line bg-surface px-5 text-sm font-semibold text-body",
                "shadow-(--shadow-soft) transition-colors duration-200",
                "hover:border-line-strong hover:bg-hover",
                "disabled:cursor-not-allowed disabled:opacity-60"
              )}
            >
              {busy ? (
                <Loader2 className="size-[18px] shrink-0 animate-spin" aria-hidden />
              ) : (
                <ProviderMark provider={p.id} />
              )}
              {verb} {p.label}
            </button>
          );
        })}
      </div>

      {error && (
        <div
          role="alert"
          className="mt-3 rounded-xl border border-fail-line bg-fail-soft p-3.5 text-[13px] leading-relaxed text-fail"
        >
          {error}
        </div>
      )}
    </div>
  );
}

/** "or" rule between the social block and the email form. */
export function AuthDivider({ label = "or" }: { label?: string }) {
  return (
    <div className="my-6 flex items-center gap-3" aria-hidden>
      <span className="h-px flex-1 bg-line" />
      <span className="text-[11.5px] font-semibold tracking-wider text-faint uppercase">
        {label}
      </span>
      <span className="h-px flex-1 bg-line" />
    </div>
  );
}

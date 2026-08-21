/** Social sign-in providers.
 *
 * Supabase Auth (GoTrue) performs the OAuth dance; this app only names the
 * provider and handles the return trip. That is why no client id or secret
 * appears anywhere in this codebase — see `docs/oauth-setup` notes in
 * `.env.example`. Every NEXT_PUBLIC_* value is compiled into the browser
 * bundle, so a provider secret placed here would be public.
 *
 * Which providers appear is env-driven: a button for a provider that has not
 * been configured in Supabase is a dead end, so the list is opt-in rather
 * than hardcoded. */

import type { Provider } from "@supabase/supabase-js";

export interface OAuthProvider {
  /** The key Supabase knows the provider by. */
  id: Provider;
  label: string;
  /** Extra scopes beyond the provider default, space separated. */
  scopes?: string;
}

/** Everything this app knows how to render. Order is the display order. */
export const OAUTH_PROVIDERS: readonly OAuthProvider[] = [
  { id: "google", label: "Google" },
  // Facebook returns no email unless it is asked for explicitly, and an
  // account with no email cannot be granted workspace access.
  { id: "facebook", label: "Facebook", scopes: "email" },
  // `slack_oidc` is Sign in with Slack (OpenID Connect). The older `slack`
  // provider is deprecated by Supabase and rejects new Slack apps.
  { id: "slack_oidc", label: "Slack" },
] as const;

const BY_ID = new Map(OAUTH_PROVIDERS.map((p) => [p.id as string, p]));

/**
 * Providers enabled for this deployment, from NEXT_PUBLIC_AUTH_PROVIDERS
 * (comma separated, e.g. `google,facebook,slack_oidc`).
 *
 * Unset means all known providers — the common case, and it keeps a fresh
 * clone working without extra configuration. An explicit empty value turns
 * social sign-in off entirely, which is how you disable it without deleting
 * the buttons.
 */
export function enabledProviders(): OAuthProvider[] {
  const raw = process.env.NEXT_PUBLIC_AUTH_PROVIDERS;
  if (raw === undefined) return [...OAUTH_PROVIDERS];
  return raw
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean)
    // "slack" is accepted as an alias so the env file can use the friendly
    // name without silently selecting the deprecated provider.
    .map((s) => (s === "slack" ? "slack_oidc" : s))
    .map((s) => BY_ID.get(s))
    .filter((p): p is OAuthProvider => Boolean(p));
}

/**
 * Absolute URL Supabase sends the browser back to after the provider
 * approves. Must be listed under Authentication → URL Configuration →
 * Redirect URLs in Supabase, or the redirect is refused.
 *
 * NEXT_PUBLIC_SITE_URL exists because `window.location.origin` is wrong in
 * exactly the case that matters: behind a proxy or a preview deployment the
 * browser's origin is not the origin registered with the provider.
 */
export function oauthRedirectUrl(next?: string | null): string {
  const configured = process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/+$/, "");
  const origin =
    configured || (typeof window !== "undefined" ? window.location.origin : "");
  const url = new URL(`${origin}/auth/callback`);
  // Carried through the round trip so a user who was deep-linked lands back
  // where they were headed rather than on the dashboard.
  if (next && next.startsWith("/")) url.searchParams.set("next", next);
  return url.toString();
}

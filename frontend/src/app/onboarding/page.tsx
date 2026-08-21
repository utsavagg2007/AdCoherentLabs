"use client";

/** First-organization screen. The form is fully wired to POST /v1/orgs —
 * but the current backend rejects users with zero memberships before that
 * route can run, so that outcome gets a calm, honest provisioning state
 * instead of a fake failure or an infinite spinner. No direct SQL/RPC writes.
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Building2, ShieldQuestion } from "lucide-react";
import { Logo } from "@/components/logo";
import { Button } from "@/components/ui/button";
import { PageLoading } from "@/components/ui/feedback";
import { ApiClient, isApiError } from "@/lib/api";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";

type Phase =
  | "checking"
  | "form"
  | "submitting"
  | "needs_provisioning"
  | "error";

export default function OnboardingPage() {
  const router = useRouter();
  const configured = supabaseConfigured();
  const [phase, setPhase] = useState<Phase>("checking");
  const [name, setName] = useState("");
  const [email, setEmail] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const api = useMemo(
    () =>
      new ApiClient({
        getToken: async () => {
          const { data } = await getSupabase().auth.getSession();
          return data.session?.access_token ?? null;
        },
        getOrgId: () => null,
      }),
    []
  );

  useEffect(() => {
    if (!configured) {
      router.replace("/login");
      return;
    }
    let cancelled = false;
    (async () => {
      const { data } = await getSupabase().auth.getSession();
      if (cancelled) return;
      if (!data.session) {
        router.replace("/login?next=/onboarding");
        return;
      }
      setEmail(data.session.user.email ?? null);
      // RLS-safe discovery: members with an org skip onboarding entirely.
      const { data: memberships, error: membershipError } = await getSupabase()
        .from("memberships")
        .select("org_id")
        .limit(1);
      if (cancelled) return;
      if (memberships && memberships.length > 0) {
        router.replace("/dashboard");
        return;
      }
      if (membershipError) {
        // RLS read unavailable — ask the authoritative backend instead
        try {
          const me = await api.orgMe();
          if (cancelled) return;
          if (me.memberships.length > 0) {
            router.replace("/dashboard");
            return;
          }
        } catch {
          /* zero memberships (403) or backend unreachable — show the form */
        }
      }
      if (cancelled) return;
      setPhase("form");
    })();
    return () => {
      cancelled = true;
    };
  }, [configured, router, api]);

  async function createOrg(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setPhase("submitting");
    setErrorMsg(null);
    try {
      await api.createOrg(name.trim());
      router.replace("/dashboard");
    } catch (err) {
      if (isApiError(err) && err.status === 403) {
        // The backend's auth gate currently rejects zero-membership users
        // before org creation can execute — administrator provisioning is
        // the honest path until that's resolved.
        setPhase("needs_provisioning");
        return;
      }
      setErrorMsg(
        isApiError(err) ? err.message : "The workspace could not be created."
      );
      setPhase("error");
    }
  }

  async function signOut() {
    await getSupabase().auth.signOut();
    router.replace("/login");
  }

  if (phase === "checking") {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-canvas">
        <PageLoading label="Preparing your workspace" />
      </div>
    );
  }

  return (
    <div className="min-h-dvh bg-canvas">
      <header className="container-page flex h-16 items-center justify-between">
        <Link href="/" className="rounded-lg">
          <Logo tone="dark" />
        </Link>
        <button
          onClick={signOut}
          className="text-[13px] font-semibold text-subtle hover:text-strong"
        >
          Sign out{email ? ` (${email})` : ""}
        </button>
      </header>

      <main className="container-page flex justify-center pt-[8vh] pb-16">
        {phase === "needs_provisioning" ? (
          <div className="bg-dots w-full max-w-md rounded-3xl border border-line bg-surface p-8 text-center shadow-(--shadow-soft)">
            <div className="mx-auto flex size-14 items-center justify-center rounded-2xl border border-line-strong bg-tint text-muted">
              <ShieldQuestion className="size-6" aria-hidden />
            </div>
            <h1 className="mt-5 text-xl font-extrabold tracking-tight text-strong">
              Workspace setup needs administrator provisioning
            </h1>
            <p className="mx-auto mt-3 max-w-sm text-sm leading-relaxed text-subtle">
              Your account is confirmed, but self-serve workspace creation
              isn&apos;t available for brand-new accounts yet. An administrator
              needs to provision your first organization — or add you to an
              existing one. Once that happens, sign in again and you&apos;ll
              land straight on your dashboard.
            </p>
            <div className="mt-7 flex flex-col items-center gap-3">
              <Button variant="secondary" onClick={() => setPhase("form")}>
                Try again
              </Button>
              <a
                href="mailto:support@adcoherentlabs.com?subject=Workspace%20provisioning"
                className="text-[13px] font-semibold text-strong hover:text-brand-text"
              >
                Contact support
              </a>
            </div>
          </div>
        ) : (
          <div className="w-full max-w-md">
            <div className="rounded-3xl border border-line bg-surface p-8 shadow-(--shadow-soft)">
              <div className="flex size-12 items-center justify-center rounded-2xl border border-line-strong bg-tint text-muted">
                <Building2 className="size-5" aria-hidden />
              </div>
              <h1 className="mt-5 text-2xl font-extrabold tracking-tight text-strong">
                Name your workspace
              </h1>
              <p className="mt-2 text-sm leading-relaxed text-subtle">
                Your organization holds your team, credits, and every review
                trail. You can rename it later.
              </p>
              <form onSubmit={createOrg} className="mt-6 space-y-4">
                <div>
                  <label htmlFor="org-name" className="label">
                    Organization name
                  </label>
                  <input
                    id="org-name"
                    className="input"
                    required
                    maxLength={120}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Acme Financial"
                    autoFocus
                  />
                </div>
                {phase === "error" && errorMsg && (
                  <div role="alert" className="rounded-xl border border-fail-line bg-fail-soft p-3.5 text-[13px] leading-relaxed text-fail">
                    {errorMsg}
                  </div>
                )}
                <Button
                  type="submit"
                  className="w-full"
                  size="lg"
                  loading={phase === "submitting"}
                  disabled={!name.trim()}
                >
                  Create workspace
                </Button>
              </form>
            </div>
            <p className="mt-4 text-center text-[12.5px] leading-relaxed text-subtle">
              Starts on the Free plan — 25 credits monthly. Reviews are
              decision support, not legal advice.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}

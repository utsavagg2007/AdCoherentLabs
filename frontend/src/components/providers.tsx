"use client";

/** Session + organization context for the authenticated app.
 *
 * Supabase: authentication, session refresh, RLS-safe membership discovery.
 * FastAPI: everything else. The selected org is persisted locally but the
 * backend re-verifies membership on every request — the header only selects
 * among the caller's own orgs. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { Session } from "@supabase/supabase-js";
import { ApiClient, isApiError } from "@/lib/api";
import { getSupabase, supabaseConfigured } from "@/lib/supabase";
import type { Role } from "@/lib/types";

const ORG_STORAGE_KEY = "adcoherent.selected-org";

/** Session-global latest-org selection, read by the API client at request
 * time. Written only from event handlers and async continuations — the
 * React state (`orgId`) remains the render source of truth. */
const orgSelection = { id: null as string | null };

/** Fallback membership discovery through the authoritative backend, used
 * when the RLS read is unavailable. Handles the multi-org 400 (org_ids in
 * details), stale persisted org ids (404), and zero-membership 403. */
async function discoverViaApi(api: ApiClient): Promise<OrgOption[]> {
  const toOptions = (me: Awaited<ReturnType<ApiClient["orgMe"]>>): OrgOption[] =>
    me.memberships.map((m) => ({
      org_id: m.org_id,
      role: m.role,
      name: m.org_id === me.org.id ? me.org.name : "Workspace",
    }));
  try {
    return toOptions(await api.orgMe());
  } catch (e) {
    if (isApiError(e) && e.status === 404 && orgSelection.id) {
      // persisted org no longer among memberships — retry unselected
      orgSelection.id = null;
      return toOptions(await api.orgMe());
    }
    if (isApiError(e) && e.status === 400) {
      const ids = e.details["org_ids"];
      if (Array.isArray(ids) && ids.length > 0) {
        let stored: string | null = null;
        try {
          stored = localStorage.getItem(ORG_STORAGE_KEY);
        } catch {
          /* storage unavailable */
        }
        orgSelection.id =
          stored && ids.includes(stored) ? stored : (ids[0] as string);
        return toOptions(await api.orgMe());
      }
    }
    if (isApiError(e) && e.status === 403) return []; // zero memberships
    throw e;
  }
}

// ---------------------------------------------------------------- auth

interface AuthContextValue {
  session: Session | null;
  loading: boolean;
  configured: boolean;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AppProviders>");
  return ctx;
}

// ---------------------------------------------------------------- org

export interface OrgOption {
  org_id: string;
  role: Role;
  name: string;
}

interface OrgContextValue {
  orgs: OrgOption[];
  orgId: string | null;
  role: Role | null;
  orgName: string | null;
  loadingOrgs: boolean;
  selectOrg: (orgId: string) => void;
  refreshOrgs: () => Promise<void>;
  api: ApiClient;
}

const OrgContext = createContext<OrgContextValue | null>(null);

export function useOrg(): OrgContextValue {
  const ctx = useContext(OrgContext);
  if (!ctx) throw new Error("useOrg must be used inside <AppProviders>");
  return ctx;
}

export function useApi(): ApiClient {
  return useOrg().api;
}

// ---------------------------------------------------------------- provider

export function AppProviders({ children }: { children: React.ReactNode }) {
  const configured = supabaseConfigured();
  const [session, setSession] = useState<Session | null>(null);
  // unconfigured environments are never "loading" — resolved at first render
  const [loading, setLoading] = useState(configured);

  useEffect(() => {
    if (!configured) return;
    const supabase = getSupabase();
    let cancelled = false;
    supabase.auth.getSession().then(({ data }) => {
      if (!cancelled) {
        setSession(data.session);
        setLoading(false);
      }
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, s) => {
      setSession(s);
      setLoading(false);
    });
    return () => {
      cancelled = true;
      sub.subscription.unsubscribe();
    };
  }, [configured]);

  const signOut = useCallback(async () => {
    if (configured) await getSupabase().auth.signOut();
    orgSelection.id = null;
    try {
      localStorage.removeItem(ORG_STORAGE_KEY);
    } catch {
      /* storage unavailable */
    }
  }, [configured]);

  // ---- org discovery (RLS-safe read; backend stays authoritative) ----
  const [orgs, setOrgs] = useState<OrgOption[]>([]);
  const [orgId, setOrgId] = useState<string | null>(null);
  const [loadingOrgs, setLoadingOrgs] = useState(true);

  const api = useMemo(
    () =>
      new ApiClient({
        getToken: async () => {
          if (!configured) return null;
          const { data } = await getSupabase().auth.getSession();
          return data.session?.access_token ?? null;
        },
        getOrgId: () => orgSelection.id,
      }),
    [configured]
  );

  // WHO is signed in, not WHICH session object. supabase-js mints a brand new
  // Session on every token refresh — and it refreshes whenever the tab regains
  // focus. Keying discovery on `session` therefore rebuilt `loadOrgs`, re-ran
  // the effect below, flipped `loadingOrgs` back to true, and the app shell
  // (app/layout.tsx) unmounted the whole page for "Opening your workspace".
  // That is what made switching tabs look like a full page reload and threw
  // away in-progress state such as the review transcript.
  const userId = session?.user?.id ?? null;

  const loadOrgs = useCallback(async (isStale: () => boolean = () => false) => {
    // called via a microtask so state updates never run synchronously
    // inside the invoking effect
    await Promise.resolve();
    if (!configured || !userId) {
      orgSelection.id = null;
      setOrgs([]);
      setOrgId(null);
      setLoadingOrgs(false);
      return;
    }
    if (isStale()) return;
    setLoadingOrgs(true);
    try {
      const { data, error } = await getSupabase()
        .from("memberships")
        .select("org_id, role, orgs ( name )")
        .order("created_at", { ascending: true });
      if (error) throw error;
      if (isStale()) return;
      const options: OrgOption[] = (data ?? []).map((row) => {
        const rel = row.orgs as { name?: string } | { name?: string }[] | null;
        const name = Array.isArray(rel) ? rel[0]?.name : rel?.name;
        return {
          org_id: row.org_id as string,
          role: row.role as Role,
          name: name ?? "Workspace",
        };
      });
      setOrgs(options);
      let stored: string | null = null;
      try {
        stored = localStorage.getItem(ORG_STORAGE_KEY);
      } catch {
        /* storage unavailable */
      }
      const valid =
        (stored && options.find((o) => o.org_id === stored)?.org_id) ||
        options[0]?.org_id ||
        null;
      orgSelection.id = valid;
      setOrgId(valid);
    } catch {
      // PostgREST unavailable — fall back to the authoritative backend for
      // membership discovery (org names beyond the selected org are not
      // exposed there; the switcher shows a generic label for those).
      try {
        const fallback = await discoverViaApi(api);
        if (isStale()) return;
        setOrgs(fallback);
        let stored: string | null = null;
        try {
          stored = localStorage.getItem(ORG_STORAGE_KEY);
        } catch {
          /* storage unavailable */
        }
        const valid =
          (stored && fallback.find((o) => o.org_id === stored)?.org_id) ||
          fallback[0]?.org_id ||
          null;
        orgSelection.id = valid;
        setOrgId(valid);
      } catch {
        // Both discovery paths failed: no-org state; individual API calls
        // surface the real errors.
        if (!isStale()) setOrgs([]);
      }
    } finally {
      if (!isStale()) setLoadingOrgs(false);
    }
  }, [configured, userId, api]);

  useEffect(() => {
    // Discovery waits until the auth session has settled — a run started
    // against a stale session must never publish its result (it would
    // briefly claim "no orgs" and bounce the app to onboarding).
    if (loading) return;
    let stale = false;
    const t = setTimeout(() => void loadOrgs(() => stale), 0);
    return () => {
      stale = true;
      clearTimeout(t);
    };
  }, [loadOrgs, loading]);

  const selectOrg = useCallback((id: string) => {
    orgSelection.id = id;
    setOrgId(id);
    try {
      localStorage.setItem(ORG_STORAGE_KEY, id);
    } catch {
      /* storage unavailable */
    }
  }, []);

  const current = orgs.find((o) => o.org_id === orgId) ?? null;

  const authValue = useMemo(
    () => ({ session, loading, configured, signOut }),
    [session, loading, configured, signOut]
  );
  const orgValue = useMemo(
    () => ({
      orgs,
      orgId,
      role: current?.role ?? null,
      orgName: current?.name ?? null,
      loadingOrgs,
      selectOrg,
      refreshOrgs: loadOrgs,
      api,
    }),
    [orgs, orgId, current?.role, current?.name, loadingOrgs, selectOrg, loadOrgs, api]
  );

  return (
    <AuthContext.Provider value={authValue}>
      <OrgContext.Provider value={orgValue}>{children}</OrgContext.Provider>
    </AuthContext.Provider>
  );
}

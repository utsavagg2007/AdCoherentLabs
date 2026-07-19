"use client";

/** Browser Supabase client — auth, RLS-safe reads, realtime, signed URLs.
 * Business writes never go through this client; FastAPI owns them. */

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let client: SupabaseClient | null = null;

export function supabaseConfigured(): boolean {
  return Boolean(
    process.env.NEXT_PUBLIC_SUPABASE_URL &&
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
  );
}

export function getSupabase(): SupabaseClient {
  if (!client) {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (!url || !anon) {
      throw new Error(
        "Supabase is not configured. Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY."
      );
    }
    client = createClient(url, anon, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
        flowType: "pkce",
        storageKey: "adcoherent-auth",
      },
    });
  }
  return client;
}

/** Short-lived signed URL for a stored creative (RLS: org members only). */
export async function signedAssetUrl(
  storagePath: string,
  expiresInSeconds = 300
): Promise<string | null> {
  try {
    const { data, error } = await getSupabase()
      .storage.from("assets")
      .createSignedUrl(storagePath, expiresInSeconds);
    if (error) return null;
    return data?.signedUrl ?? null;
  } catch {
    return null;
  }
}

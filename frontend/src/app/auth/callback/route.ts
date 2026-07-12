import { NextResponse } from "next/server";
import type { EmailOtpType } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/server";

/**
 * Handles every GoTrue redirect: OAuth + PKCE (?code=), and email links
 * (?token_hash=&type=) for confirmation, invites, magic links and recovery.
 */
export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const tokenHash = url.searchParams.get("token_hash");
  const type = url.searchParams.get("type") as EmailOtpType | null;
  const next = safeNext(url.searchParams.get("next"));

  const supabase = await createClient();

  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(new URL(destination(type, next), url.origin));
    }
  } else if (tokenHash && type) {
    const { error } = await supabase.auth.verifyOtp({
      type,
      token_hash: tokenHash,
    });
    if (!error) {
      return NextResponse.redirect(new URL(destination(type, next), url.origin));
    }
  }

  return NextResponse.redirect(
    new URL(
      "/login?error=" +
        encodeURIComponent("That link is invalid or expired — try again."),
      url.origin,
    ),
  );
}

function destination(type: EmailOtpType | null, next: string) {
  if (type === "recovery") return "/reset-password";
  return next;
}

function safeNext(next: string | null): string {
  // Only allow same-origin relative paths — never an open redirect.
  if (next && next.startsWith("/") && !next.startsWith("//")) return next;
  return "/dashboard";
}

import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

const PROTECTED_PREFIXES = [
  "/dashboard",
  "/submissions",
  "/runs",
  "/reports",
  "/billing",
  "/settings",
  "/onboarding",
];

// Signed-in users are bounced away from these (reset-password is excluded:
// the recovery link signs the user in first).
const AUTH_PAGES = ["/login", "/signup", "/forgot-password"];

export default async function proxy(request: NextRequest) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const demo = process.env.NEXT_PUBLIC_DEMO_MODE === "true" || !url || !anonKey;

  // Demo mode: the whole product is browsable, no session to manage.
  if (demo) return NextResponse.next();

  let response = NextResponse.next({ request });

  const supabase = createServerClient(url, anonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) =>
          request.cookies.set(name, value),
        );
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options),
        );
      },
    },
  });

  // Also refreshes an expired session — do not remove.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const path = request.nextUrl.pathname;

  const redirectTo = (target: string) => {
    const dest = new URL(target, request.url);
    const redirected = NextResponse.redirect(dest);
    // Preserve any refreshed auth cookies on the redirect.
    response.cookies
      .getAll()
      .forEach((c) => redirected.cookies.set(c.name, c.value, c));
    return redirected;
  };

  if (!user && PROTECTED_PREFIXES.some((p) => path.startsWith(p))) {
    const next = encodeURIComponent(path + request.nextUrl.search);
    return redirectTo(`/login?next=${next}`);
  }

  if (user && AUTH_PAGES.some((p) => path.startsWith(p))) {
    return redirectTo("/dashboard");
  }

  return response;
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|api/billing/webhook|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};

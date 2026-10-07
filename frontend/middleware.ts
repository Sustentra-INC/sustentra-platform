import { NextResponse, type NextRequest } from "next/server";

import { loginUrlFor, parseRealm, REALM_COOKIE } from "./lib/realm-cookie";
import { SESSION_COOKIE } from "./lib/session-cookie";

/**
 * Edge auth guard (FE-001). A fast UX redirect only — it checks for the presence
 * of the `__Host-session` cookie and bounces unauthenticated visitors to the
 * right login page. It does NOT validate the session; the API enforces real
 * authorization, and protected server layouts re-check via `/api/v1/auth/me`
 * (see `lib/auth-guard.ts`).
 *
 * Guards:
 *   - `/` (the workpaper)  → the login of the realm last signed in to on this
 *                            browser (`sustentra_realm` cookie), else `/sign-in` (FE-006)
 *   - `/provider-admin/*`  → `/provider-admin/login`
 *   - `/org/[slug]/*`      → `/org/[slug]/login`
 * Public auth pages under an org (login / forgot-password / reset-password) and
 * the provider login stay reachable without a session.
 */

export { SESSION_COOKIE };

// Pages under /org/[slug] that must stay open to signed-out visitors.
const PUBLIC_ORG_PAGE = /^\/org\/[^/]+\/(login|forgot-password|reset-password)\/?$/;

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  const hasSession = request.cookies.has(SESSION_COOKIE);
  if (hasSession) return NextResponse.next();

  // The workpaper: no org in the URL, so use the remembered realm. The fixture demo
  // (NEXT_PUBLIC_S1_DATA_MODE=fixture) has its own demo sign-in and stays open.
  if (pathname === "/" && process.env.NEXT_PUBLIC_S1_DATA_MODE !== "fixture") {
    const realm = parseRealm(request.cookies.get(REALM_COOKIE)?.value);
    const url = request.nextUrl.clone();
    const target = new URL(loginUrlFor(realm, "/" + request.nextUrl.search), url);
    url.pathname = target.pathname;
    url.search = target.search;
    return NextResponse.redirect(url);
  }

  // Provider admin area.
  if (pathname === "/provider-admin" || pathname.startsWith("/provider-admin/")) {
    if (pathname === "/provider-admin/login") return NextResponse.next();
    return redirectTo(request, "/provider-admin/login", pathname);
  }

  // Org area: /org/[slug]/...
  const orgMatch = pathname.match(/^\/org\/([^/]+)(?:\/.*)?$/);
  if (orgMatch) {
    if (PUBLIC_ORG_PAGE.test(pathname)) return NextResponse.next();
    return redirectTo(request, `/org/${orgMatch[1]}/login`, pathname);
  }

  return NextResponse.next();
}

function redirectTo(request: NextRequest, loginPath: string, from: string): NextResponse {
  const url = request.nextUrl.clone();
  url.pathname = loginPath;
  url.search = "";
  url.searchParams.set("next", from);
  return NextResponse.redirect(url);
}

export const config = {
  matcher: ["/", "/provider-admin/:path*", "/org/:path*"],
};

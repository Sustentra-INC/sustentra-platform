import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE } from "./lib/session-cookie";

/**
 * Edge auth guard (FE-001). A fast UX redirect only — it checks for the presence
 * of the `__Host-session` cookie and bounces unauthenticated visitors to the
 * right login page. It does NOT validate the session; the API enforces real
 * authorization, and protected server layouts re-check via `/api/v1/auth/me`
 * (see `lib/auth-guard.ts`).
 *
 * Guards:
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
  matcher: ["/provider-admin/:path*", "/org/:path*"],
};

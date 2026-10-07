import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import { SESSION_COOKIE } from "./session-cookie";

/**
 * Server-side auth guard (FE-001). Protected server layouts call `requireSession`
 * which re-validates the session against the API (`/api/v1/auth/me`) and redirects
 * on 401 or wrong role. The edge middleware is UX-only; this is the real check.
 */

export type Role = "provider_admin" | "org_admin" | "org_member";

export interface Me {
  id: string;
  email: string;
  role: Role;
  org_id?: string | null;
  org_slug?: string | null;
  first_name?: string;
  last_name?: string;
}

// Server-to-server base URL. Prefer an internal URL (not browser-exposed); fall
// back to the public one, then localhost for dev.
const API_URL =
  process.env.BACKEND_INTERNAL_URL ?? process.env.NEXT_PUBLIC_BACKEND_API_URL ?? "http://localhost:8000";

/** The API could not confirm the session either way (429, 5xx, network). Not a
 *  sign-out: rendering fails (app/error.tsx) instead of bouncing to login. */
export class SessionCheckError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SessionCheckError";
  }
}

/**
 * One `/auth/me` call per session token per server render (AUTH-007): a layout
 * and its page both guarding the same request share the result (React `cache`).
 */
const fetchMe = cache(async (token: string): Promise<Me | null> => {
  let response: Response;
  try {
    response = await fetch(`${API_URL}/api/v1/auth/me`, {
      headers: { cookie: `${SESSION_COOKIE}=${token}` },
      cache: "no-store",
    });
  } catch {
    throw new SessionCheckError("Could not reach the API to check the session.");
  }
  // Only a definite "no" signs the user out.
  if (response.status === 401 || response.status === 403) return null;
  if (!response.ok) throw new SessionCheckError(`Session check failed (${response.status}).`);
  return (await response.json()) as Me;
});

/** Fetch the current user from the API using the forwarded session cookie, or
 *  null when signed out. Throws SessionCheckError when the API can't tell. */
export async function getMe(): Promise<Me | null> {
  const store = await cookies();
  const session = store.get(SESSION_COOKIE);
  if (!session?.value) return null;
  return fetchMe(session.value);
}

export interface RequireSessionOptions {
  /** Allowed role(s). Omit to allow any authenticated user. */
  role?: Role | Role[];
  /** Where to send a signed-out visitor. Defaults to the provider login. */
  loginPath?: string;
  /** Where to send a signed-in user whose role is not allowed. */
  forbiddenPath?: string;
}

/**
 * Enforce an authenticated session (and optionally a role) in a server layout.
 * Redirects (throws) on failure; returns the user on success.
 */
export async function requireSession(options: RequireSessionOptions = {}): Promise<Me> {
  const me = await getMe();
  if (!me) redirect(options.loginPath ?? "/provider-admin/login");

  if (options.role) {
    const allowed = Array.isArray(options.role) ? options.role : [options.role];
    if (!allowed.includes(me.role)) redirect(options.forbiddenPath ?? "/");
  }

  return me;
}

/**
 * Where a signed-in user who may NOT see `/org/{slug}/...` should go instead, or
 * null when they may (FE-005):
 *   - provider admins manage orgs in the provider portal (the org pages need an org session),
 *   - a user of another org goes to their own org's home (never a different org's pages),
 *   - an org_member on an admin page goes to the org home.
 */
export function orgAreaRedirect(me: Me, slug: string, { admin }: { admin: boolean }): string | null {
  if (me.role === "provider_admin") return "/provider-admin/orgs";
  if (!me.org_slug || me.org_slug !== slug) return me.org_slug ? `/org/${me.org_slug}` : "/sign-in";
  if (admin && me.role !== "org_admin") return `/org/${slug}`;
  return null;
}

/** Guard for `/org/{slug}/...` server components. Signed out -> the org's login. */
export async function requireOrgArea(
  slug: string,
  { admin }: { admin: boolean },
): Promise<Me & { org_id: string }> {
  const me = await requireSession({ loginPath: `/org/${slug}/login` });
  const elsewhere = orgAreaRedirect(me, slug, { admin });
  if (elsewhere) redirect(elsewhere);
  return me as Me & { org_id: string };
}

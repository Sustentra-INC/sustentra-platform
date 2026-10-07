import { encodeRealm, isOrgSlug, parseRealm, REALM_COOKIE } from "../../lib/realm-cookie";
import { loginPath, type Realm } from "./realm";

/**
 * The realm a user last signed in to on this browser (FE-007). The workpaper at
 * `/` has no org in its URL, so when its session ends it uses this to send the
 * user back to the right login page. Only the realm is stored — the org slug is
 * part of public URLs, never a secret — and storage failures are ignored.
 */

const KEY = "sustentra.lastRealm";
const ONE_YEAR = 60 * 60 * 24 * 365;

export function rememberRealm(realm: Realm): void {
  const value = encodeRealm(realm);
  // Cookie: lets the edge middleware send a signed-out "/" to the right login (FE-006).
  try {
    const secure = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `${REALM_COOKIE}=${encodeURIComponent(value)}; Path=/; Max-Age=${ONE_YEAR}; SameSite=Lax${secure}`;
  } catch {
    // Cookies blocked: the sign-in page asks for the organization instead.
  }
  try {
    window.localStorage.setItem(KEY, value);
  } catch {
    // Private mode / blocked storage: the workpaper falls back to its sign-in panel.
  }
}

function realmCookie(): string | null {
  try {
    const match = document.cookie.split("; ").find((part) => part.startsWith(`${REALM_COOKIE}=`));
    return match ? decodeURIComponent(match.slice(REALM_COOKIE.length + 1)) : null;
  } catch {
    return null;
  }
}

export function lastRealm(): Realm | null {
  const fromCookie = parseRealm(realmCookie());
  if (fromCookie) return fromCookie;
  try {
    return parseRealm(window.localStorage.getItem(KEY));
  } catch {
    return null;
  }
}

/** `/…/login?next=<path>` for a realm. */
export function signInPath(realm: Realm, next: string): string {
  return `${loginPath(realm)}?next=${encodeURIComponent(next)}`;
}

/** A post-login destination from `?next=`, only if it is a same-origin path. */
export function safeNext(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return null;
  if (/[\u0000-\u001f]/.test(next)) return null;
  return next;
}

export { isOrgSlug };

import { loginPath, type Realm } from "./realm";

/**
 * The realm a user last signed in to on this browser (FE-007). The workpaper at
 * `/` has no org in its URL, so when its session ends it uses this to send the
 * user back to the right login page. Only the realm is stored — the org slug is
 * part of public URLs, never a secret — and storage failures are ignored.
 */

const KEY = "sustentra.lastRealm";
const SLUG = /^[a-z0-9-]{3,63}$/; // same rule as the backend (provider_orgs.SLUG_PATTERN)

export function rememberRealm(realm: Realm): void {
  try {
    window.localStorage.setItem(KEY, realm.kind === "org" ? `org:${realm.slug}` : "provider");
  } catch {
    // Private mode / blocked storage: the workpaper falls back to its sign-in panel.
  }
}

export function lastRealm(): Realm | null {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
  if (raw === "provider") return { kind: "provider" };
  if (raw?.startsWith("org:")) {
    const slug = raw.slice(4);
    if (SLUG.test(slug)) return { kind: "org", slug };
  }
  return null;
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

/** Whether a string is a valid org slug (for the workpaper's sign-in panel). */
export function isOrgSlug(value: string): boolean {
  return SLUG.test(value);
}

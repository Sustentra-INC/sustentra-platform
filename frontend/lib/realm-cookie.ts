/**
 * The realm (org slug or provider) a browser last signed in to (FE-006). Not a
 * secret — org slugs are in public URLs — and not an authorization signal: the
 * edge middleware only uses it to pick which login page to show for `/`.
 * Values: `org:<slug>` or `provider`.
 */
export const REALM_COOKIE = "sustentra_realm";

export type RealmValue = { kind: "provider" } | { kind: "org"; slug: string };

const SLUG = /^[a-z0-9-]{3,63}$/; // same rule as the backend (provider_orgs.SLUG_PATTERN)

export function isOrgSlug(value: string): boolean {
  return SLUG.test(value);
}

export function encodeRealm(realm: RealmValue): string {
  return realm.kind === "org" ? `org:${realm.slug}` : "provider";
}

export function parseRealm(raw: string | null | undefined): RealmValue | null {
  if (raw === "provider") return { kind: "provider" };
  if (raw?.startsWith("org:")) {
    const slug = raw.slice(4);
    if (isOrgSlug(slug)) return { kind: "org", slug };
  }
  return null;
}

/**
 * A post-login destination, only if it is a path inside this app: starts with a single "/", has no
 * backslash and no control characters. Anything else (another site, a protocol-relative "//host") is
 * not a destination, so `?next=` cannot be used as an open redirect.
 */
export function sameOriginPath(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) return null;
  if (/[\u0000-\u001f\u007f]/.test(next)) return null;
  return next;
}

/** The login page for a realm (or the realm-agnostic `/sign-in`), returning to `next` (a path, query included). */
export function loginUrlFor(realm: RealmValue | null, next: string): string {
  next = sameOriginPath(next) ?? "/";
  const base = realm === null ? "/sign-in" : realm.kind === "org" ? `/org/${realm.slug}/login` : "/provider-admin/login";
  return `${base}?next=${encodeURIComponent(next)}`;
}

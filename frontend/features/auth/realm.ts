/**
 * An auth "realm" — the two login contexts in the MVP. Provider admins sign in
 * at `/provider-admin/*`; organisation users sign in under their org slug at
 * `/org/[slug]/*`. These helpers centralise the per-realm paths and request
 * fields so the shared auth components stay DRY.
 */
export type Realm = { kind: "provider" } | { kind: "org"; slug: string };

/** Extra request fields that scope an auth call to the right realm. */
export function realmBody(realm: Realm): Record<string, string> {
  return realm.kind === "org" ? { org_slug: realm.slug } : {};
}

export function basePath(realm: Realm): string {
  return realm.kind === "org" ? `/org/${realm.slug}` : "/provider-admin";
}

export function loginPath(realm: Realm): string {
  return `${basePath(realm)}/login`;
}

export function forgotPath(realm: Realm): string {
  return `${basePath(realm)}/forgot-password`;
}

export function resetPath(realm: Realm): string {
  return `${basePath(realm)}/reset-password`;
}

/** Where a successful login lands. */
export function homePath(realm: Realm): string {
  return realm.kind === "org" ? `/org/${realm.slug}` : "/provider-admin/orgs";
}

export function realmTitle(realm: Realm): string {
  return realm.kind === "org" ? "Sign in" : "Provider admin";
}

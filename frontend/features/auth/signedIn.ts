import type { Me } from "../../lib/auth-guard";
import { safeNext } from "./lastRealm";
import { homePath, type Realm } from "./realm";

/**
 * Where a login page sends a visitor who is already signed in to that realm, or null to
 * show the login. Reaching a login page signed in happens through the browser's Back
 * button after signing in: the login (and its code step) must not come back until the
 * user signs out.
 */
export function signedInRedirect(me: Me | null, realm: Realm, next: string | null | undefined): string | null {
  if (!me) return null;
  const sameRealm =
    realm.kind === "provider" ? me.role === "provider_admin" : me.role !== "provider_admin" && me.org_slug === realm.slug;
  return sameRealm ? (safeNext(next) ?? homePath(realm)) : null;
}

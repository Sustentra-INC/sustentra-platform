import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { S1WorkpaperApp } from "../features/s1/pages/S1WorkpaperApp";
import { getMe } from "../lib/auth-guard";
import { loginUrlFor, parseRealm, REALM_COOKIE } from "../lib/realm-cookie";

/**
 * The product home: the S1 evidence workpaper. Fixture vs. live data is chosen
 * at runtime by `NEXT_PUBLIC_S1_DATA_MODE` (fixture | backend) inside
 * `S1WorkpaperApp`; see docs/frontend_backend_integration.md.
 *
 * Backend mode needs a session (FE-006): the edge middleware redirects when the
 * cookie is missing, and this re-checks it against the API, so an expired or
 * revoked session also lands on the right login page.
 */
export default async function HomePage() {
  if (process.env.NEXT_PUBLIC_S1_DATA_MODE === "fixture") return <S1WorkpaperApp />;

  const me = await getMe();
  if (!me) {
    const realm = parseRealm((await cookies()).get(REALM_COOKIE)?.value);
    redirect(loginUrlFor(realm, "/"));
  }
  return (
    <S1WorkpaperApp
      user={{ email: me.email, firstName: me.first_name ?? null, role: me.role, orgSlug: me.org_slug ?? null }}
    />
  );
}

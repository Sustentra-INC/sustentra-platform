import type { ReactNode } from "react";

import { requireSession } from "../../../lib/auth-guard";

/** Guards the whole provider-admin orgs area — only `provider_admin` may enter.
 *  The API re-enforces this; this is the server-side redirect. */
export default async function ProviderOrgsLayout({ children }: { children: ReactNode }) {
  await requireSession({ role: "provider_admin", loginPath: "/provider-admin/login" });
  return <>{children}</>;
}

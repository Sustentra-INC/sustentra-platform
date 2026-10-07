import type { ReactNode } from "react";

import { requireOrgArea } from "../../../../lib/auth-guard";

/** Every org admin page (FE-005): org_admin of THIS org only. Members go to the
 *  org home, users of another org to their own org, provider admins to their
 *  portal. The API re-enforces all of it; this is the server-side redirect. */
export default async function OrgAdminLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  await requireOrgArea(slug, { admin: true });
  return <>{children}</>;
}

import { requireSession } from "../../../../../lib/auth-guard";
import { AuditLog } from "../../../../../features/admin/AuditLog";

export default async function AuditLogPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const me = await requireSession({
    role: ["org_admin", "provider_admin"],
    loginPath: `/org/${slug}/login`,
    forbiddenPath: `/org/${slug}`,
  });
  return <AuditLog orgId={me.org_id ?? ""} />;
}

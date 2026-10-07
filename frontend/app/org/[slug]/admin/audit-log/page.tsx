import { requireOrgArea } from "../../../../../lib/auth-guard";
import { AuditLog } from "../../../../../features/admin/AuditLog";

export default async function AuditLogPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const me = await requireOrgArea(slug, { admin: true });
  return <AuditLog orgId={me.org_id} />;
}

import { requireOrgArea } from "../../../../../../lib/auth-guard";
import { InviteUserForm } from "../../../../../../features/admin/InviteUserForm";

export default async function InviteUserPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const me = await requireOrgArea(slug, { admin: true });
  return <InviteUserForm orgId={me.org_id} slug={slug} />;
}

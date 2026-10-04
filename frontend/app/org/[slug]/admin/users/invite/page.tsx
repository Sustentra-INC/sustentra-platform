import { requireSession } from "../../../../../../lib/auth-guard";
import { InviteUserForm } from "../../../../../../features/admin/InviteUserForm";

export default async function InviteUserPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const me = await requireSession({
    role: ["org_admin", "provider_admin"],
    loginPath: `/org/${slug}/login`,
    forbiddenPath: `/org/${slug}`,
  });
  return <InviteUserForm orgId={me.org_id ?? ""} slug={slug} />;
}

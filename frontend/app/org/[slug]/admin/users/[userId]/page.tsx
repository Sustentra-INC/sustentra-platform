import { requireSession } from "../../../../../../lib/auth-guard";
import { UserDetail } from "../../../../../../features/admin/UserDetail";

export default async function UserDetailPage({
  params,
}: {
  params: Promise<{ slug: string; userId: string }>;
}) {
  const { slug, userId } = await params;
  const me = await requireSession({
    role: ["org_admin", "provider_admin"],
    loginPath: `/org/${slug}/login`,
    forbiddenPath: `/org/${slug}`,
  });
  return <UserDetail orgId={me.org_id ?? ""} slug={slug} userId={userId} />;
}

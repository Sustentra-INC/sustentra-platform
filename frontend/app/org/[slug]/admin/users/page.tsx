import { requireSession } from "../../../../../lib/auth-guard";
import { UsersList } from "../../../../../features/admin/UsersList";

export default async function OrgUsersPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const me = await requireSession({
    role: ["org_admin", "provider_admin"],
    loginPath: `/org/${slug}/login`,
    forbiddenPath: `/org/${slug}`,
  });
  return <UsersList orgId={me.org_id ?? ""} slug={slug} />;
}

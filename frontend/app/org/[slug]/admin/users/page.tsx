import { requireOrgArea } from "../../../../../lib/auth-guard";
import { UsersList } from "../../../../../features/admin/UsersList";

export default async function OrgUsersPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { slug } = await params;
  const { deleted } = await searchParams;
  const me = await requireOrgArea(slug, { admin: true });
  return <UsersList orgId={me.org_id} slug={slug} notice={deleted === "1" ? "User deleted." : null} />;
}

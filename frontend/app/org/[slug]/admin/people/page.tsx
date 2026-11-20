import { requireOrgArea } from "../../../../../lib/auth-guard";
import { PeopleList } from "../../../../../features/admin/PeopleList";

export default async function OrgPeoplePage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { slug } = await params;
  const { add } = await searchParams;
  const me = await requireOrgArea(slug, { admin: true });
  return <PeopleList orgId={me.org_id} startAdding={add === "1"} />;
}

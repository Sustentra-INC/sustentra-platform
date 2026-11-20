import { requireOrgArea } from "../../../../../lib/auth-guard";
import { OrgTasks } from "../../../../../features/tasks/OrgTasks";

export default async function OrgTasksPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const me = await requireOrgArea(slug, { admin: true });
  return <OrgTasks orgId={me.org_id} slug={slug} />;
}

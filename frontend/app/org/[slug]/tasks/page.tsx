import { requireOrgArea } from "../../../../lib/auth-guard";
import { MyTasks } from "../../../../features/tasks/MyTasks";

export default async function MyTasksPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const me = await requireOrgArea(slug, { admin: false });
  return <MyTasks orgId={me.org_id} slug={slug} />;
}

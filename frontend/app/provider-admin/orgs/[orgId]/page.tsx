import { OrgDetail } from "../../../../features/admin/OrgDetail";

export default async function OrgDetailPage({ params }: { params: Promise<{ orgId: string }> }) {
  const { orgId } = await params;
  return <OrgDetail orgId={orgId} />;
}

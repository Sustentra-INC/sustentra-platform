import { requireSession } from "../../../lib/auth-guard";
import { OrgHome } from "../../../features/admin/OrgHome";

export default async function OrgHomePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const me = await requireSession({ loginPath: `/org/${slug}/login` });
  return <OrgHome me={me} slug={slug} />;
}

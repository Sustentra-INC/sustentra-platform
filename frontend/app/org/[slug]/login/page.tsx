import { LoginFlow } from "../../../../features/auth/LoginFlow";

export default async function OrgLoginPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <LoginFlow realm={{ kind: "org", slug }} />;
}

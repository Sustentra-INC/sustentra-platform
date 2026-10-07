import { LoginFlow } from "../../../../features/auth/LoginFlow";

export default async function OrgLoginPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { slug } = await params;
  const { next } = await searchParams;
  return <LoginFlow realm={{ kind: "org", slug }} next={typeof next === "string" ? next : null} />;
}

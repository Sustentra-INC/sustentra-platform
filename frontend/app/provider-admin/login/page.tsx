import { LoginFlow } from "../../../features/auth/LoginFlow";

export default async function ProviderLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { next } = await searchParams;
  return <LoginFlow realm={{ kind: "provider" }} next={typeof next === "string" ? next : null} />;
}

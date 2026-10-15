import { redirect } from "next/navigation";

import { LoginFlow } from "../../../features/auth/LoginFlow";
import { signedInRedirect } from "../../../features/auth/signedIn";
import { getMe, SessionCheckError } from "../../../lib/auth-guard";

export default async function ProviderLoginPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { next } = await searchParams;
  // Signed in already (e.g. Back after signing in): go on instead of showing the login again.
  const me = await getMe().catch((error: unknown) => {
    if (error instanceof SessionCheckError) return null; // the API can't tell: the login stays reachable
    throw error;
  });
  const goTo = signedInRedirect(me, { kind: "provider" }, typeof next === "string" ? next : null);
  if (goTo) redirect(goTo);
  return <LoginFlow realm={{ kind: "provider" }} next={typeof next === "string" ? next : null} />;
}

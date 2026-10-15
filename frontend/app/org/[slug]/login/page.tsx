import { redirect } from "next/navigation";

import { ACCOUNT_READY_NOTICE, LoginFlow } from "../../../../features/auth/LoginFlow";
import { signedInRedirect } from "../../../../features/auth/signedIn";
import { getMe, SessionCheckError } from "../../../../lib/auth-guard";

export default async function OrgLoginPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { slug } = await params;
  const { next, status } = await searchParams;
  // Signed in already (e.g. Back after signing in): go on instead of showing the login again.
  const me = await getMe().catch((error: unknown) => {
    if (error instanceof SessionCheckError) return null; // the API can't tell: the login stays reachable
    throw error;
  });
  const goTo = signedInRedirect(me, { kind: "org", slug }, typeof next === "string" ? next : null);
  if (goTo) redirect(goTo);
  return (
    <LoginFlow
      realm={{ kind: "org", slug }}
      next={typeof next === "string" ? next : null}
      // Set by the accept-invite page after the account is activated (FE-003).
      initialNotice={status === "ready" ? ACCOUNT_READY_NOTICE : null}
    />
  );
}

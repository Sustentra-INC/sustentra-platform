import { ACCOUNT_READY_NOTICE, LoginFlow } from "../../../../features/auth/LoginFlow";

export default async function OrgLoginPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { slug } = await params;
  const { next, status } = await searchParams;
  return (
    <LoginFlow
      realm={{ kind: "org", slug }}
      next={typeof next === "string" ? next : null}
      // Set by the accept-invite page after the account is activated (FE-003).
      initialNotice={status === "ready" ? ACCOUNT_READY_NOTICE : null}
    />
  );
}

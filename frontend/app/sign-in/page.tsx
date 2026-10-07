import { SessionEndedPanel } from "../../features/s1/components/SessionEndedPanel";
import { safeNext } from "../../features/auth/lastRealm";

/**
 * Realm-agnostic sign-in (FE-006): where a signed-out visit to the workpaper goes
 * when the browser does not know the user's organization. Asks for it and sends
 * the user to that org's login (or the provider login), then back to `next`.
 */
export default async function SignInPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { next } = await searchParams;
  return (
    <SessionEndedPanel
      next={safeNext(typeof next === "string" ? next : null) ?? "/"}
      title="Sign in"
      subtitle="Enter your organization to continue to its sign-in page."
    />
  );
}

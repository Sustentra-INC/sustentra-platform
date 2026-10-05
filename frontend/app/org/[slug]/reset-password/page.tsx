import { Suspense } from "react";

import { ResetPasswordForm } from "../../../../features/auth/ResetPasswordForm";

export default async function OrgResetPasswordPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return (
    <Suspense>
      <ResetPasswordForm realm={{ kind: "org", slug }} />
    </Suspense>
  );
}

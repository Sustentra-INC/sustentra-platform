import { Suspense } from "react";

import { ResetPasswordForm } from "../../../features/auth/ResetPasswordForm";

export default function ProviderResetPasswordPage() {
  return (
    <Suspense>
      <ResetPasswordForm realm={{ kind: "provider" }} />
    </Suspense>
  );
}

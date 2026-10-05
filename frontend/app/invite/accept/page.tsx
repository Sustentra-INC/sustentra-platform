import { Suspense } from "react";

import { AcceptInviteForm } from "../../../features/auth/AcceptInviteForm";

export default function AcceptInvitePage() {
  return (
    <Suspense>
      <AcceptInviteForm />
    </Suspense>
  );
}

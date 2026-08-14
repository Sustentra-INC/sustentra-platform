"use client";

import { usePathname } from "next/navigation";

/**
 * The reassurance line at the foot of the client screens.
 *
 * Hidden on the review queue: "your answers are saved as you go" is addressed
 * to the client filling the form, and showing it to a Sustentra reviewer is
 * talking to the wrong person.
 */
const REVIEW = "/intake/review";

export function IntakeFootnote() {
  const pathname = usePathname() ?? "";
  if (pathname === REVIEW || pathname.startsWith(`${REVIEW}/`)) return null;

  return (
    <footer className="intake-footnote">
      <p>Your answers are saved as you go. You can stop and come back at any time.</p>
    </footer>
  );
}

import type { ReactNode } from "react";

import "./intake.css";

interface IntakeLayoutProps {
  children: ReactNode;
}

/**
 * Wrapper for the client-facing intake screens.
 *
 * This nests inside the existing root layout, so the internal sidebar is still
 * visible. Giving intake its own full-page shell would mean restructuring the
 * existing app/layout.tsx, which is out of bounds without approval.
 */
export default function IntakeLayout({ children }: IntakeLayoutProps) {
  return <div className="intake">{children}</div>;
}

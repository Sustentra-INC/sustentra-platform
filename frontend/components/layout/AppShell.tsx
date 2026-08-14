"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { AppSidebar } from "./AppSidebar";
import { PageHeader } from "./PageHeader";

/**
 * Chooses the frame for a page.
 *
 * The internal surface keeps the sidebar and header it has always had. The
 * client-facing intake screens get neither: a client onboarding to Sustentra
 * must not see internal navigation, and certainly not a banner reading
 * "Production skeleton". They get the page and nothing else.
 *
 * Split by path rather than by a prop so no existing page had to change.
 */
const CLIENT_FACING = "/intake";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? "";

  if (pathname === CLIENT_FACING || pathname.startsWith(`${CLIENT_FACING}/`)) {
    return <>{children}</>;
  }

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <AppSidebar />
      <main style={{ flex: 1, padding: 20 }}>
        <PageHeader
          title="Sustentra Evidence Extraction"
          subtitle="Production skeleton: Next.js frontend + FastAPI backend"
        />
        {children}
      </main>
    </div>
  );
}

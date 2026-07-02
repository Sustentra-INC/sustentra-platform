import type { ReactNode } from "react";

import { AppSidebar } from "../components/layout/AppSidebar";
import { PageHeader } from "../components/layout/PageHeader";

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "Segoe UI, Arial, sans-serif" }}>
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
      </body>
    </html>
  );
}


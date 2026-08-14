import type { ReactNode } from "react";

import { AppShell } from "../components/layout/AppShell";

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "Segoe UI, Arial, sans-serif" }}>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}

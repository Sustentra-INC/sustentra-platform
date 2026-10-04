import type { ReactNode } from "react";

import "../features/s1/styles/sustentra-tokens.css";
import "../features/s1/styles/s1-workpaper.css";

/**
 * Root layout. The Sustentra product surface (the S1 workpaper) lives at `/` and
 * brings its own in-app chrome (left sidebar + context bar) from `S1Chrome`, so
 * the root layout stays minimal and just loads the design-system tokens and the
 * workpaper styles. The Sustentra-internal admin pages (login / clients / users
 * / account) add their own `AppShell` via the `(admin)` route group layout.
 */
interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

import type { ReactNode } from "react";
import "../features/s1/styles/sustentra-tokens.css";
import "../features/s1/styles/s1-workpaper.css";

/**
 * Type is the classic neutral grotesque (Helvetica Neue / Helvetica / Arial),
 * taken straight from the system so it renders as real Helvetica on the Mac the
 * demo is presented from, and metric-identical Arial elsewhere. Defined on the
 * --font-sans / --font-mono tokens.
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

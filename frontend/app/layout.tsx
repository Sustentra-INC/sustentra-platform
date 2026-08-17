import type { ReactNode } from "react";
import "../features/s1/styles/sustentra-tokens.css";
import "../features/s1/styles/s1-workpaper.css";
import "../features/s2/styles/s2-workpaper.css";

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

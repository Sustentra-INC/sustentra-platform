import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import "../features/s1/styles/sustentra-tokens.css";
import "../features/s1/styles/s1-workpaper.css";

/**
 * Root layout. The Sustentra product surface (the S1 workpaper) lives at `/` and
 * brings its own in-app chrome (left sidebar + context bar) from `S1Chrome`, so
 * the root layout stays minimal and just loads the design-system tokens and the
 * workpaper styles. The provider and org admin areas (/provider-admin, /org/[slug])
 * are separate route trees with their own layouts.
 */
// Favicon / app icons come from the Next.js file conventions in this folder:
// favicon.ico, icon.png and apple-icon.png (generated from public/sustentra-mark.png).
export const metadata: Metadata = {
  title: { default: "Sustentra", template: "%s · Sustentra" },
  description: "Sustentra: evidence-backed sustainability assurance workpapers.",
  applicationName: "Sustentra",
};

export const viewport: Viewport = {
  themeColor: "#2b2b77", // logo navy
};

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

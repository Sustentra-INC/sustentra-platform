import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import type { ReactNode } from "react";

import "../features/s1/styles/sustentra-tokens.css";
import "../features/s1/styles/s1-workpaper.css";
import "../features/s1/styles/s1-demo-documents.css";

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
  themeColor: "#3A40C0", // brand indigo
};

// The interface font: Inter, loaded from Google Fonts via next/font and exposed as
// --font-inter so the --font-sans stack in sustentra-tokens.css resolves to it.
// IBM Plex Sans files remain in ./fonts (SIL OFL 1.1, see ./fonts/OFL.txt) but are
// no longer loaded; they can be removed in a later cleanup ticket.
const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-inter",
  display: "swap",
});

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en" className={inter.variable}>
      <body>{children}</body>
    </html>
  );
}

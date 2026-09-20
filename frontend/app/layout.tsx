import type { ReactNode } from "react";
import { IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "../features/s1/styles/sustentra-tokens.css";
import "../features/s1/styles/s1-workpaper.css";

/**
 * Type is self-hosted via next/font (downloaded at build, served from our own
 * deploy) so it works offline after first load and never flashes a fallback.
 * IBM Plex Sans/Mono: an engineered, software-grade family — the mono carries
 * every figure, ID and coordinate the workpaper shows.
 */
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-ibm-plex-sans",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-ibm-plex-mono",
  display: "swap",
});

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="en" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}

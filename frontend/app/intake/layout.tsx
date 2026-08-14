import type { ReactNode } from "react";
import { Newsreader, Public_Sans } from "next/font/google";

import { IntakeFootnote } from "../../components/intake/IntakeFootnote";

import "./intake.css";

/**
 * The client-facing shell.
 *
 * These screens no longer render inside the internal sidebar and the
 * "Production skeleton" banner - AppShell hands intake routes the page and
 * nothing else - so this is the whole frame a client sees.
 *
 * The type pairing is deliberate. A serif for headings makes the page read as a
 * document rather than a dashboard, which is what this is: a record someone
 * will eventually verify. Both faces are downloaded at build time and served
 * from this app, so no request leaves the browser for a font.
 */
const heading = Newsreader({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-heading",
  display: "swap"
});

const body = Public_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-body",
  display: "swap"
});

interface IntakeLayoutProps {
  children: ReactNode;
}

export default function IntakeLayout({ children }: IntakeLayoutProps) {
  return (
    <div className={`${heading.variable} ${body.variable} intake intake-shell`}>
      <header className="intake-masthead">
        <span className="intake-wordmark">Sustentra</span>
      </header>
      <main className="intake-main">{children}</main>
      <IntakeFootnote />
    </div>
  );
}

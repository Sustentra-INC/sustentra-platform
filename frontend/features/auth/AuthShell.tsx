import type { ReactNode } from "react";

import styles from "./auth.module.css";

/** Split-panel auth layout used by every auth page (login / forgot / reset / activate). */
export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className={styles.authLayout}>
      <section className={styles.brandPanel} aria-label="Sustentra">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className={styles.brandLogo} src="/sustentra-logo.png" alt="Sustentra" />
        <div className={styles.brandCopy}>
          <h2 className={styles.brandHeadline}>
            AI operation system for environmental compliance.
          </h2>
          <p className={styles.brandTagline}>Climate evidence, always assurance-ready.</p>
        </div>
      </section>
      <main className={styles.formSide}>
        <div className={styles.formInner}>
          <div className={styles.heading}>
            <h1 className={styles.title}>{title}</h1>
            {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
          </div>
          {children}
          {footer}
        </div>
      </main>
    </div>
  );
}

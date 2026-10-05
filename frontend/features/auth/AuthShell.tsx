import type { ReactNode } from "react";

import styles from "./auth.module.css";

/** Centered auth card used by every auth page (login / forgot / reset). */
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
    <main className={styles.page}>
      <div className={styles.card}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className={styles.logo} src="/sustentra-logo.png" alt="Sustentra" />
        <div className={styles.heading}>
          <h1 className={styles.title}>{title}</h1>
          {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
        </div>
        {children}
        {footer}
      </div>
    </main>
  );
}

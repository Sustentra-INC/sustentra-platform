"use client";

import Link from "next/link";

import { logout } from "../auth/api";
import type { Me } from "./orgApi";
import styles from "./admin.module.css";

/** The authenticated org home (FE-005): who you are + sign out, plus admin links
 *  for admins. Org users land on the workpaper after login (FE-006); this page is
 *  reached from its "Admin" link and links back. */
export function OrgHome({ me, slug }: { me: Me; slug: string }) {
  const isAdmin = me.role === "org_admin" || me.role === "provider_admin";
  const name = me.first_name ? `Welcome, ${me.first_name}` : "Welcome";

  async function onSignOut() {
    try {
      await logout();
    } catch {
      // Clear client state regardless.
    }
    window.location.assign(`/org/${slug}/login`);
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>{name}</h1>
          <p className={styles.subtitle}>
            {me.email} · {me.role.replace("_", " ")}
          </p>
        </div>
        <button type="button" className={`${styles.button} ${styles.ghost}`} onClick={onSignOut}>
          Sign out
        </button>
      </div>
      <div className={styles.actions}>
        <Link className={styles.button} href="/">
          Open workpaper
        </Link>
      </div>
      {isAdmin ? (
        <div className={styles.actions}>
          <Link className={styles.button} href={`/org/${slug}/admin/users`}>
            Manage users
          </Link>
          <Link className={`${styles.button} ${styles.ghost}`} href={`/org/${slug}/admin/audit-log`}>
            Audit log
          </Link>
        </div>
      ) : (
        <p className={styles.muted}>You’re signed in.</p>
      )}
    </div>
  );
}

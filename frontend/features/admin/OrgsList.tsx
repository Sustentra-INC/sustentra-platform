"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { listOrgs, type Org, type OrgStatus } from "./providerApi";
import { StatusBadge } from "./StatusBadge";
import styles from "./admin.module.css";

/** Provider-admin organisations list (FE-004): search + status filter. */
export function OrgsList() {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<OrgStatus | "">("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const page = await listOrgs({ search, status });
      setOrgs(page.items);
    } catch {
      setError("Could not load organizations.");
    } finally {
      setLoading(false);
    }
  }, [search, status]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Organizations</h1>
          <p className={styles.subtitle}>All client organizations on Sustentra.</p>
        </div>
        <Link className={styles.button} href="/provider-admin/orgs/new">
          + New organization
        </Link>
      </div>

      <form
        className={styles.toolbar}
        onSubmit={(e) => {
          e.preventDefault();
          void load();
        }}
      >
        <input
          className={`${styles.input} ${styles.grow}`}
          placeholder="Search name or slug"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search organizations"
        />
        <select
          className={styles.select}
          value={status}
          onChange={(e) => setStatus(e.target.value as OrgStatus | "")}
          aria-label="Filter by status"
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="suspended">Suspended</option>
        </select>
        <button type="submit" className={`${styles.button} ${styles.ghost}`}>
          Search
        </button>
      </form>

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Name</th>
              <th>Slug</th>
              <th>Status</th>
              <th>Seats</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={4} className={styles.muted}>
                  Loading…
                </td>
              </tr>
            ) : orgs.length === 0 ? (
              <tr>
                <td colSpan={4} className={styles.muted}>
                  No organizations found.
                </td>
              </tr>
            ) : (
              orgs.map((org) => (
                <tr key={org.id}>
                  <td>
                    <Link className={styles.rowLink} href={`/provider-admin/orgs/${org.id}`}>
                      {org.name}
                    </Link>
                  </td>
                  <td className={styles.muted}>{org.slug}</td>
                  <td>
                    <StatusBadge status={org.status} />
                  </td>
                  <td>
                    {org.user_count ?? "—"} / {org.max_users}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

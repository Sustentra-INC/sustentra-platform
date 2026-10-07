"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { listOrgs, type Org, type OrgStatus } from "./providerApi";
import { StatusBadge } from "./StatusBadge";
import styles from "./admin.module.css";

/** Provider-admin organisations list (FE-004): search + status filter, paginated. */
export function OrgsList() {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<OrgStatus | "">("");
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [reloadKey, setReloadKey] = useState(0);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Refetch whenever the filters (or reloadKey) change. State is only set once
  // the request settles, so the effect never calls setState synchronously
  // (react-hooks/set-state-in-effect); `loading` is derived from whether the
  // latest request has finished.
  const requestKey = JSON.stringify([search, status, page, reloadKey]);
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let active = true;
    listOrgs({ search, status, page })
      .then((res) => {
        if (!active) return;
        setOrgs(res.items);
        setPages(Math.max(1, Math.ceil(res.total / res.page_size)));
        setError(null);
      })
      .catch(() => {
        if (active) setError("Could not load organizations.");
      })
      .finally(() => {
        if (active) setLoadedKey(requestKey);
      });
    return () => {
      active = false;
    };
    // requestKey captures every input of the request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey]);

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
          setReloadKey((k) => k + 1);
        }}
      >
        <input
          className={`${styles.input} ${styles.grow}`}
          placeholder="Search name or slug"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
          aria-label="Search organizations"
        />
        <select
          className={styles.select}
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as OrgStatus | "");
            setPage(1);
          }}
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

      {pages > 1 ? (
        <nav className={styles.toolbar} aria-label="Pages">
          <button
            type="button"
            className={`${styles.button} ${styles.ghost}`}
            onClick={() => setPage((p) => p - 1)}
            disabled={page <= 1 || loading}
          >
            Previous
          </button>
          <span className={styles.muted}>
            Page {page} of {pages}
          </span>
          <button
            type="button"
            className={`${styles.button} ${styles.ghost}`}
            onClick={() => setPage((p) => p + 1)}
            disabled={page >= pages || loading}
          >
            Next
          </button>
        </nav>
      ) : null}
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { listOrgUsers, type OrgUser, type UserRole, type UserStatus } from "./orgApi";
import { StatusBadge } from "./StatusBadge";
import styles from "./admin.module.css";

/** Org users list (FE-005): status/role filters, seat usage, invite button. */
export function UsersList({ orgId, slug }: { orgId: string; slug: string }) {
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [seats, setSeats] = useState<{ used: number; max: number } | null>(null);
  const [status, setStatus] = useState<UserStatus | "">("");
  const [role, setRole] = useState<UserRole | "">("");
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Refetch whenever the filters change. State is only set once
  // the request settles, so the effect never calls setState synchronously
  // (react-hooks/set-state-in-effect); `loading` is derived from whether the
  // latest request has finished.
  const requestKey = JSON.stringify([orgId, status, role]);
  const loading = loadedKey !== requestKey;

  useEffect(() => {
    let active = true;
    listOrgUsers(orgId, { status, role })
      .then((res) => {
        if (!active) return;
        setUsers(res.items);
        setSeats({ used: res.total, max: res.max_users });
        setError(null);
      })
      .catch(() => {
        if (active) setError("Could not load users.");
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
          <h1 className={styles.title}>Users</h1>
          <p className={styles.subtitle}>
            {seats ? `${seats.used} / ${seats.max} seats used` : "Manage your team."}
          </p>
        </div>
        <Link className={styles.button} href={`/org/${slug}/admin/users/invite`}>
          + Invite user
        </Link>
      </div>

      <div className={styles.toolbar}>
        <select
          className={styles.select}
          value={status}
          onChange={(e) => setStatus(e.target.value as UserStatus | "")}
          aria-label="Filter by status"
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="invited">Invited</option>
          <option value="suspended">Suspended</option>
        </select>
        <select
          className={styles.select}
          value={role}
          onChange={(e) => setRole(e.target.value as UserRole | "")}
          aria-label="Filter by role"
        >
          <option value="">All roles</option>
          <option value="org_admin">Admin</option>
          <option value="org_member">Member</option>
        </select>
      </div>

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
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={4} className={styles.muted}>
                  Loading…
                </td>
              </tr>
            ) : users.length === 0 ? (
              <tr>
                <td colSpan={4} className={styles.muted}>
                  No users found.
                </td>
              </tr>
            ) : (
              users.map((user) => (
                <tr key={user.id}>
                  <td>
                    <Link className={styles.rowLink} href={`/org/${slug}/admin/users/${user.id}`}>
                      {`${user.first_name} ${user.last_name}`.trim() || user.email}
                    </Link>
                  </td>
                  <td className={styles.muted}>{user.email}</td>
                  <td>{user.role === "org_admin" ? "Admin" : "Member"}</td>
                  <td>
                    <StatusBadge status={user.status} />
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

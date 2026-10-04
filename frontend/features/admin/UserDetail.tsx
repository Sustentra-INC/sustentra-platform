"use client";

import { useEffect, useState } from "react";

import { ApiError } from "../../lib/api";
import {
  deleteUser,
  getOrgUser,
  reactivateUser,
  resendInvite,
  suspendUser,
  updateUserRole,
  type OrgUser,
  type UserRole,
} from "./orgApi";
import { ConfirmByTyping } from "./ConfirmByTyping";
import { StatusBadge } from "./StatusBadge";
import styles from "./admin.module.css";

/** User detail (FE-005): change role, suspend/reactivate, delete, resend invite.
 *  Suspend and delete confirm by typing the email; resend only for `invited`. */
export function UserDetail({ orgId, userId }: { orgId: string; slug: string; userId: string }) {
  const [user, setUser] = useState<OrgUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<null | "suspend" | "delete">(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setUser(await getOrgUser(orgId, userId));
    } catch {
      setError("Could not load this user.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, userId]);

  function runAction(action: () => Promise<void>, okMessage: string) {
    return async () => {
      setError(null);
      setNotice(null);
      try {
        await action();
        setNotice(okMessage);
        await load();
      } catch (err) {
        setError(err instanceof ApiError ? err.detail : "Something went wrong.");
      }
    };
  }

  async function onRoleChange(role: UserRole) {
    setError(null);
    setNotice(null);
    try {
      setUser(await updateUserRole(orgId, userId, role));
      setNotice("Role updated.");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Could not change the role.");
    }
  }

  if (loading) {
    return (
      <div className={styles.page}>
        <p className={styles.muted}>Loading…</p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className={styles.page}>
        <p className={styles.error} role="alert">
          {error ?? "User not found."}
        </p>
      </div>
    );
  }

  const fullName = `${user.first_name} ${user.last_name}`.trim() || user.email;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>{fullName}</h1>
          <p className={styles.subtitle}>
            {user.email} · <StatusBadge status={user.status} />
          </p>
        </div>
      </div>

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}
      {notice ? <p className={styles.muted}>{notice}</p> : null}

      <div className={styles.card}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="role">
            Role
          </label>
          <select
            id="role"
            className={styles.select}
            value={user.role}
            onChange={(e) => void onRoleChange(e.target.value as UserRole)}
          >
            <option value="org_member">Member</option>
            <option value="org_admin">Admin</option>
          </select>
        </div>

        <div className={styles.actions}>
          {user.status === "suspended" ? (
            <button
              type="button"
              className={`${styles.button} ${styles.ghost}`}
              onClick={runAction(() => reactivateUser(orgId, userId), "User reactivated.")}
            >
              Reactivate
            </button>
          ) : (
            <button
              type="button"
              className={`${styles.button} ${styles.danger}`}
              onClick={() => setConfirm("suspend")}
            >
              Suspend
            </button>
          )}
          {user.status === "invited" ? (
            <button
              type="button"
              className={`${styles.button} ${styles.ghost}`}
              onClick={runAction(() => resendInvite(orgId, userId), "Invite resent.")}
            >
              Resend invite
            </button>
          ) : null}
          <button
            type="button"
            className={`${styles.button} ${styles.danger}`}
            onClick={() => setConfirm("delete")}
          >
            Delete
          </button>
        </div>
      </div>

      {confirm === "suspend" ? (
        <ConfirmByTyping
          title="Suspend user"
          message={`${fullName} will be signed out and can't sign in until reactivated.`}
          confirmPhrase={user.email}
          confirmLabel="Suspend"
          danger
          onConfirm={() => {
            setConfirm(null);
            void runAction(() => suspendUser(orgId, userId), "User suspended.")();
          }}
          onCancel={() => setConfirm(null)}
        />
      ) : null}

      {confirm === "delete" ? (
        <ConfirmByTyping
          title="Delete user"
          message={`This removes ${fullName} from the organization.`}
          confirmPhrase={user.email}
          confirmLabel="Delete"
          danger
          onConfirm={() => {
            setConfirm(null);
            void runAction(() => deleteUser(orgId, userId), "User deleted.")();
          }}
          onCancel={() => setConfirm(null)}
        />
      ) : null}
    </div>
  );
}

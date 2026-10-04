"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";

import { ApiError } from "../../lib/api";
import { inviteUser, type UserRole } from "./orgApi";
import styles from "./admin.module.css";

/** Invite a user (FE-005). Surfaces seat-limit (422) and duplicate (409) errors. */
export function InviteUserForm({ orgId, slug }: { orgId: string; slug: string }) {
  const [email, setEmail] = useState("");
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [role, setRole] = useState<UserRole>("org_member");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [invited, setInvited] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!email.trim()) {
      setError("Enter an email address.");
      return;
    }
    setSubmitting(true);
    try {
      await inviteUser(orgId, {
        email: email.trim(),
        role,
        first_name: first.trim(),
        last_name: last.trim(),
      });
      setInvited(email.trim());
      setEmail("");
      setFirst("");
      setLast("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("That person is already in this organization.");
      } else if (err instanceof ApiError && err.status === 422) {
        setError("You've reached your seat limit. Increase it or remove a user first.");
      } else if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("Could not send the invite. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <h1 className={styles.title}>Invite a user</h1>
          <p className={styles.subtitle}>They’ll get an email to set a password and join.</p>
        </div>
      </div>

      {invited ? (
        <p className={styles.muted} role="status">
          Invite sent to {invited}.
        </p>
      ) : null}

      <form className={styles.card} onSubmit={onSubmit} noValidate>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
        <div className={styles.field}>
          <label className={styles.label} htmlFor="email">
            Email
          </label>
          <input
            id="email"
            className={styles.input}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoFocus
          />
        </div>
        <div className={styles.actions}>
          <div className={styles.field} style={{ flex: 1 }}>
            <label className={styles.label} htmlFor="first">
              First name
            </label>
            <input
              id="first"
              className={styles.input}
              value={first}
              onChange={(e) => setFirst(e.target.value)}
            />
          </div>
          <div className={styles.field} style={{ flex: 1 }}>
            <label className={styles.label} htmlFor="last">
              Last name
            </label>
            <input
              id="last"
              className={styles.input}
              value={last}
              onChange={(e) => setLast(e.target.value)}
            />
          </div>
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="role">
            Role
          </label>
          <select
            id="role"
            className={styles.select}
            value={role}
            onChange={(e) => setRole(e.target.value as UserRole)}
          >
            <option value="org_member">Member</option>
            <option value="org_admin">Admin</option>
          </select>
        </div>
        <div className={styles.actions}>
          <button type="submit" className={styles.button} disabled={submitting}>
            {submitting ? "Sending…" : "Send invite"}
          </button>
          <Link className={`${styles.button} ${styles.ghost}`} href={`/org/${slug}/admin/users`}>
            Back to users
          </Link>
        </div>
      </form>
    </div>
  );
}

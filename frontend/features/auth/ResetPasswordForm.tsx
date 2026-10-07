"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { ApiError, resetPassword, passwordPolicyMessage } from "./api";
import { forgotPath, loginPath, type Realm } from "./realm";
import { PASSWORD_HINTS, passwordIssues } from "./passwordPolicy";
import { AuthShell } from "./AuthShell";
import styles from "./auth.module.css";

const INVALID_LINK = "This link is invalid or has expired.";

/** Reset-password (FE-002). Reads the token from the query string; validates
 *  presence, password policy, and match before calling the API. */
export function ResetPasswordForm({ realm }: { realm: Realm }) {
  const token = useSearchParams().get("token");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  if (!token) {
    return (
      <AuthShell title="Invalid reset link" subtitle="This link is missing or incomplete.">
        <Link className={styles.link} href={forgotPath(realm)}>
          Request a new link
        </Link>
      </AuthShell>
    );
  }

  if (done) {
    return (
      <AuthShell title="Password updated" subtitle="You can now sign in with your new password.">
        <Link className={styles.link} href={loginPath(realm)}>
          Go to sign in
        </Link>
      </AuthShell>
    );
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!token) return; // narrows token to string (the no-token case renders above)
    setError(null);
    const issues = passwordIssues(password);
    if (issues.length > 0) {
      setError(issues[0]);
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await resetPassword(token, password);
      setDone(true);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 400 || err.status === 410)) {
        setError(INVALID_LINK);
      } else {
        setError(passwordPolicyMessage(err) ?? "Could not reset your password. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell title="Set a new password">
      <form className={styles.form} onSubmit={onSubmit} noValidate>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
        {error === INVALID_LINK ? (
          <Link className={styles.link} href={forgotPath(realm)}>
            Request a new link
          </Link>
        ) : null}
        <div className={styles.field}>
          <label className={styles.label} htmlFor="password">
            New password
          </label>
          <input
            id="password"
            className={styles.input}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            autoFocus
          />
          <ul className={styles.hints}>
            {PASSWORD_HINTS.map((hint) => (
              <li key={hint}>{hint}</li>
            ))}
          </ul>
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="confirm">
            Confirm password
          </label>
          <input
            id="confirm"
            className={styles.input}
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
          />
        </div>
        <button type="submit" className={styles.button} disabled={submitting}>
          {submitting ? "Saving…" : "Update password"}
        </button>
      </form>
    </AuthShell>
  );
}

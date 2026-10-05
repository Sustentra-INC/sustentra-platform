"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";

import { requestPasswordReset } from "./api";
import { loginPath, type Realm } from "./realm";
import { AuthShell } from "./AuthShell";
import styles from "./auth.module.css";

/** Forgot-password (FE-002). Always shows the same neutral confirmation so it
 *  never reveals whether an account exists for the address. */
export function ForgotPasswordForm({ realm }: { realm: Realm }) {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!email.trim()) return;
    setSubmitting(true);
    try {
      await requestPasswordReset(realm, email.trim());
    } catch {
      // Neutral by design — the UI is identical whether or not the email exists.
    } finally {
      setSubmitting(false);
      setSubmitted(true);
    }
  }

  if (submitted) {
    return (
      <AuthShell
        title="Check your email"
        subtitle="If an account exists for that address, we've sent a link to reset your password."
      >
        <Link className={styles.link} href={loginPath(realm)}>
          Back to sign in
        </Link>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Reset your password" subtitle="Enter your email and we'll send a reset link.">
      <form className={styles.form} onSubmit={onSubmit} noValidate>
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
            autoComplete="username"
            autoFocus
          />
        </div>
        <button type="submit" className={styles.button} disabled={submitting}>
          {submitting ? "Sending…" : "Send reset link"}
        </button>
        <Link className={styles.link} href={loginPath(realm)}>
          Back to sign in
        </Link>
      </form>
    </AuthShell>
  );
}

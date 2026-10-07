"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";

import { ApiError, acceptInvite, validateInvite, type InviteDetails, passwordPolicyMessage } from "./api";
import { PASSWORD_HINTS, passwordIssues } from "./passwordPolicy";
import { AuthShell } from "./AuthShell";
import styles from "./auth.module.css";

type State = { status: "loading" } | { status: "invalid" } | { status: "ready"; invite: InviteDetails };

/** Accept-invite (FE-003). Validates the token on load, pre-fills the invitee's
 *  details, and takes a new password to activate the account. */
export function AcceptInviteForm({ onAccepted }: { onAccepted?: (path: string) => void }) {
  const token = useSearchParams().get("token");
  const [fetchedState, setState] = useState<State>({ status: "loading" });
  // No token in the URL means the link is invalid; derive that instead of
  // setting it inside the effect (react-hooks/set-state-in-effect).
  const state: State = token ? fetchedState : { status: "invalid" };
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!token) return;
    let active = true;
    validateInvite(token)
      .then((invite) => active && setState({ status: "ready", invite }))
      .catch(() => active && setState({ status: "invalid" }));
    return () => {
      active = false;
    };
  }, [token]);

  if (state.status === "loading") {
    return (
      <AuthShell title="Checking your invite…">
        <p className={styles.muted}>One moment.</p>
      </AuthShell>
    );
  }

  if (state.status === "invalid") {
    return (
      <AuthShell
        title="This invite link is invalid or has expired"
        subtitle="Ask your administrator to send you a new invite."
      >
        <span className={styles.muted}>Invite links expire after a while and can only be used once.</span>
      </AuthShell>
    );
  }

  const { invite } = state;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
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
      await acceptInvite(token, password);
      const go = onAccepted ?? ((path: string) => window.location.assign(path));
      go(`/org/${invite.org_slug}/login?status=ready`);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 400 || err.status === 410)) {
        setError("This invite link is invalid or has expired. Ask your administrator to resend it.");
      } else {
        setError(passwordPolicyMessage(err) ?? "Could not set up your account. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell title={`Join ${invite.org_name}`} subtitle="Set a password to activate your account.">
      <form className={styles.form} onSubmit={onSubmit} noValidate>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
        <div className={styles.field}>
          <label className={styles.label} htmlFor="invitee-name">
            Name
          </label>
          <input
            id="invitee-name"
            className={styles.input}
            value={`${invite.first_name} ${invite.last_name}`}
            readOnly
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="invitee-email">
            Email
          </label>
          <input id="invitee-email" className={styles.input} value={invite.email} readOnly />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="password">
            Password
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
          {submitting ? "Setting up…" : "Activate account"}
        </button>
      </form>
    </AuthShell>
  );
}

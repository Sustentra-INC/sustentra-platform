"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";

import { ApiError, acceptInvite, validateInvite, type InviteDetails, passwordPolicyMessage } from "./api";
import { PASSWORD_MIN_LENGTH, PASSWORD_HINTS, passwordIssues } from "./passwordPolicy";
import { AuthShell } from "./AuthShell";
import { IconCheck } from "../s1/components/icons";
import styles from "./auth.module.css";

type State = { status: "loading" } | { status: "invalid" } | { status: "ready"; invite: InviteDetails };

/** Derives up to two uppercase initials from an org name (e.g. "Northgate Provisions Inc." → "NP"). */
function orgInitials(name: string): string {
  const words = name.split(/\s+/).filter((w) => w.length > 1);
  return words
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");
}

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
  const [showPassword, setShowPassword] = useState(false);
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
  const lengthMet = password.length >= PASSWORD_MIN_LENGTH;
  const confirmTyped = confirm.length > 0;
  const passwordsMatch = password === confirm;

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
    <AuthShell
      title="Activate your account"
      header={
        <span className={styles.inviteChip} aria-label={`Invitation from ${invite.org_name}`}>
          <span className={styles.inviteAvatar} aria-hidden="true">
            {orgInitials(invite.org_name)}
          </span>
          Invitation from {invite.org_name}
        </span>
      }
    >
      <form className={styles.form} onSubmit={onSubmit} noValidate>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
        <div className={styles.field}>
          <label className="s1-field-label" htmlFor="invitee-name">
            Name
          </label>
          <input
            id="invitee-name"
            className="s1-input s1-input--lg"
            value={`${invite.first_name} ${invite.last_name}`}
            readOnly
            style={{ background: "var(--sf-card)", color: "var(--ink)", cursor: "default" }}
          />
        </div>
        <div className={styles.field}>
          <label className="s1-field-label" htmlFor="invitee-email">
            Email
          </label>
          <input
            id="invitee-email"
            className="s1-input s1-input--lg"
            value={invite.email}
            readOnly
            tabIndex={-1}
            style={{ borderColor: "var(--line)", color: "var(--ink-2)" }}
          />
        </div>
        <div className={styles.field}>
          <label className="s1-field-label" htmlFor="password">
            Password
          </label>
          <div className={styles.pwWrap}>
            <input
              id="password"
              className={styles.pwInput}
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              autoFocus
            />
            <button
              type="button"
              className={styles.pwShow}
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>
          <ul className={styles.hintList} aria-live="polite">
            <li className={`${styles.hintItem} ${lengthMet ? styles.hintMet : ""}`}>
              {lengthMet ? <IconCheck size={15} /> : null}
              {PASSWORD_HINTS[0]}
            </li>
            {/* "Not a common password" is server-side only — shown as plain text, no live check */}
            <li className={styles.hintItem}>{PASSWORD_HINTS[1]}</li>
          </ul>
        </div>
        <div className={styles.field}>
          <label className="s1-field-label" htmlFor="confirm">
            Confirm password
          </label>
          <input
            id="confirm"
            className="s1-input s1-input--lg"
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
          />
          {confirmTyped ? (
            passwordsMatch ? (
              <span className={`${styles.confirmFeedback} ${styles.confirmMatch}`}>
                <IconCheck size={15} />
                Passwords match
              </span>
            ) : (
              <span className={`${styles.confirmFeedback} ${styles.confirmMismatch}`}>
                Passwords don&apos;t match
              </span>
            )
          ) : null}
        </div>
        <button
          type="submit"
          className={`s1-button s1-button--pri s1-button--lg ${styles.submitBtn} ${styles.activateSubmit}`}
          disabled={submitting}
        >
          {submitting ? "Setting up…" : "Activate account"}
        </button>
      </form>
    </AuthShell>
  );
}

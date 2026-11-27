"use client";

import { useState } from "react";

import { AuthShell } from "../../auth/AuthShell";
import styles from "../../auth/auth.module.css";
import { isOrgSlug, signInPath } from "../../auth/lastRealm";

/**
 * Shown when the workpaper's session has ended and this browser does not know
 * which organization the user signs in to (FE-007). Asks for the org's sign-in
 * name and sends the user to that org's login, coming back here afterwards.
 */
export function SessionEndedPanel({
  next = "/",
  title = "Sign in to continue",
  subtitle = "Your session has ended. Sign in again through your organization.",
  onNavigate = (path: string) => window.location.assign(path),
}: {
  next?: string;
  title?: string;
  subtitle?: string;
  /** Injectable for tests. */
  onNavigate?: (path: string) => void;
}) {
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);

  return (
    <AuthShell title={title} subtitle={subtitle}>
      <form
        className={styles.form}
        onSubmit={(e) => {
          e.preventDefault();
          const value = slug.trim().toLowerCase();
          if (!isOrgSlug(value)) {
            setError("Enter your organization's sign-in name, e.g. acme-foods.");
            return;
          }
          onNavigate(signInPath({ kind: "org", slug: value }, next));
        }}
      >
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}

        <div className={styles.field}>
          <label className="s1-field-label" htmlFor="org-slug">
            Organization
          </label>
          <input
            id="org-slug"
            className="s1-input s1-input--lg"
            value={slug}
            onChange={(e) => {
              setSlug(e.target.value);
              setError(null);
            }}
            placeholder="acme-foods"
            autoComplete="organization"
            autoCapitalize="none"
            spellCheck={false}
          />
        </div>

        <button className={`s1-button s1-button--pri s1-button--lg ${styles.submitBtn}`} type="submit">
          Continue
        </button>

        <a className={styles.link} href={signInPath({ kind: "provider" }, next)}>
          Provider admin sign-in
        </a>
      </form>
    </AuthShell>
  );
}

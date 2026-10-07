"use client";

import { useState } from "react";

import { isOrgSlug, signInPath } from "../../auth/lastRealm";

/**
 * Shown when the workpaper's session has ended and this browser does not know
 * which organization the user signs in to (FE-007). Asks for the org's sign-in
 * name and sends the user to that org's login, coming back here afterwards.
 */
export function SessionEndedPanel({
  next = "/",
  onNavigate = (path: string) => window.location.assign(path),
}: {
  next?: string;
  /** Injectable for tests. */
  onNavigate?: (path: string) => void;
}) {
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);

  return (
    <main className="s1-signin">
      <form
        className="s1-signin__card"
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
        <div className="s1-signin__brand">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img className="s1-signin__logo" src="/sustentra-logo.png" alt="Sustentra" />
        </div>
        <h1 className="s1-signin__title">Sign in to continue</h1>
        <p className="s1-signin__sub">Your session has ended. Sign in again through your organization.</p>

        {error ? (
          <p className="s1-signin__sub" role="alert">
            {error}
          </p>
        ) : null}

        <label className="s1-signin__field">
          <span>Organization</span>
          <input
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
        </label>

        <button className="s1-signin__submit" type="submit">
          Continue
        </button>

        <div className="s1-signin__foot">
          <a className="s1-linklike" href={signInPath({ kind: "provider" }, next)}>
            Provider admin sign-in
          </a>
        </div>
      </form>
    </main>
  );
}

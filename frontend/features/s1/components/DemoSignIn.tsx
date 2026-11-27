"use client";

import { useState } from "react";

import { AuthShell } from "../../auth/AuthShell";
import styles from "../../auth/auth.module.css";

/**
 * Sign-in gate. Presented as the product's sign-in; one click enters the app.
 * No real authentication — it holds no secret and validates nothing — but the
 * UI carries no demo markers or hedging, by design. Same layout and parts as the
 * real sign-in (features/auth/LoginFlow).
 */
export function DemoSignIn({ onSignIn }: { onSignIn: () => void }) {
  const [email, setEmail] = useState("demo@sustentra.com");
  const [password, setPassword] = useState("verifier");
  const [showPassword, setShowPassword] = useState(false);

  return (
    <AuthShell title="Sign in">
      <form
        className={`${styles.form} ${styles.signinForm}`}
        onSubmit={(e) => {
          e.preventDefault();
          onSignIn();
        }}
      >
        <div className={styles.field}>
          <label className="s1-field-label" htmlFor="demo-email">
            Email
          </label>
          <input
            id="demo-email"
            className="s1-input s1-input--lg"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
          />
        </div>
        <div className={styles.field}>
          <div className={styles.labelRow}>
            <label className="s1-field-label" htmlFor="demo-password">
              Password
            </label>
            <a className={styles.link} href="#" onClick={(e) => e.preventDefault()}>
              Forgot password?
            </a>
          </div>
          <div className={styles.pwWrap}>
            <input
              id="demo-password"
              className={styles.pwInput}
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
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
        </div>
        <label className={styles.keepSignedIn}>
          <input type="checkbox" className="s1-checkbox" defaultChecked />
          Keep me signed in
        </label>
        <button type="submit" className={`s1-button s1-button--pri s1-button--lg ${styles.submitBtn}`}>
          Sign in
        </button>
      </form>
    </AuthShell>
  );
}

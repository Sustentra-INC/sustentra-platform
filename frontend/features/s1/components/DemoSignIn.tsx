"use client";

import { useState } from "react";

/**
 * Sign-in gate. Presented as the product's sign-in; one click enters the app.
 * No real authentication — it holds no secret and validates nothing — but the
 * UI carries no demo markers or hedging, by design.
 */
export function DemoSignIn({ onSignIn }: { onSignIn: () => void }) {
  const [email, setEmail] = useState("m.osei@meridian-assurance.com");
  const [password, setPassword] = useState("verifier");

  return (
    <main className="s1-signin">
      <form
        className="s1-signin__card"
        onSubmit={(e) => {
          e.preventDefault();
          onSignIn();
        }}
      >
        <div className="s1-signin__brand">Sustentra</div>
        <h1 className="s1-signin__title">Sign in</h1>
        <p className="s1-signin__sub">Verification workspace</p>

        <label className="s1-signin__field">
          <span>Email</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" />
        </label>
        <label className="s1-signin__field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </label>

        <button className="s1-signin__submit" type="submit">
          Sign in
        </button>

        <div className="s1-signin__foot">
          <span>Keep me signed in</span>
          <a className="s1-linklike" href="#" onClick={(e) => e.preventDefault()}>
            Forgot password?
          </a>
        </div>
      </form>
    </main>
  );
}

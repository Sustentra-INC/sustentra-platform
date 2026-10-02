"use client";

import { FormEvent, useEffect, useState } from "react";

import { confirmMfa, disableMfa, getMe, setupMfa } from "../../lib/api/auth";
import { ApiError } from "../../lib/api/client";
import { getActor, setSession, getToken, type Actor } from "../../lib/session";

export default function AccountPage() {
  const [actor, setActor] = useState<Actor | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [otpauth, setOtpauth] = useState<string | null>(null);
  const [devCode, setDevCode] = useState<string | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    getMe()
      .then((current) => setActor(current))
      .catch(() => setActor(getActor()));
  }, []);

  async function handleSetup() {
    setError(null);
    try {
      const result = await setupMfa();
      setSecret(result.secret);
      setOtpauth(result.otpauth_uri);
      setDevCode(result.dev_current_code ?? null);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.detail : "Could not start MFA setup.");
    }
  }

  async function handleConfirm(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const result = await confirmMfa(code);
      setRecoveryCodes(result.recovery_codes);
      setNotice("MFA is enabled. Store the recovery codes.");
      const token = getToken();
      const current = await getMe();
      setActor(current);
      if (token) setSession(token, current);
      setSecret(null);
      setCode("");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.detail : "Could not enable MFA.");
    }
  }

  async function handleDisable(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await disableMfa(password, code);
      setNotice("MFA is disabled.");
      const token = getToken();
      const current = await getMe();
      setActor(current);
      if (token) setSession(token, current);
      setPassword("");
      setCode("");
      setRecoveryCodes([]);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.detail : "Could not disable MFA.");
    }
  }

  return (
    <section>
      <h2>Account</h2>
      {actor ? (
        <p>
          Signed in as <strong>{actor.username}</strong> ({actor.actor_type})
          {actor.mfa_enabled ? " · MFA on" : " · MFA off"}
        </p>
      ) : (
        <p>Log in first.</p>
      )}
      {error ? <p style={{ color: "#a40000" }}>{error}</p> : null}
      {notice ? <p>{notice}</p> : null}

      {actor && !actor.mfa_enabled ? (
        <div>
          <button type="button" onClick={handleSetup}>Set up MFA</button>
          {secret ? (
            <form onSubmit={handleConfirm} style={{ display: "grid", gap: 8, maxWidth: 480, marginTop: 12 }}>
              <p>Add this secret to an authenticator app:</p>
              <code>{secret}</code>
              <p style={{ wordBreak: "break-all" }}>{otpauth}</p>
              {devCode ? <p>Local current code: {devCode}</p> : null}
              <input placeholder="6-digit code" value={code} onChange={(e) => setCode(e.target.value)} required />
              <button type="submit">Enable MFA</button>
            </form>
          ) : null}
        </div>
      ) : null}

      {recoveryCodes.length ? (
        <div>
          <p>Recovery codes (shown once):</p>
          <ul>
            {recoveryCodes.map((item) => (
              <li key={item}>
                <code>{item}</code>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {actor?.mfa_enabled ? (
        <form onSubmit={handleDisable} style={{ display: "grid", gap: 8, maxWidth: 420, marginTop: 24 }}>
          <strong>Disable MFA</strong>
          <input type="password" placeholder="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          <input placeholder="TOTP or recovery code" value={code} onChange={(e) => setCode(e.target.value)} required />
          <button type="submit">Disable MFA</button>
        </form>
      ) : null}
    </section>
  );
}

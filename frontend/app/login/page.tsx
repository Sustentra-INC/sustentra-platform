"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  completeMfaLogin,
  createSustentraUser,
  getAuthStatus,
  login
} from "../../lib/api/auth";
import { ApiError } from "../../lib/api/client";
import { setSession } from "../../lib/session";

export default function LoginPage() {
  const router = useRouter();
  const [bootstrap, setBootstrap] = useState(false);
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getAuthStatus()
      .then((status) => setBootstrap(status.bootstrap_required))
      .catch(() => setError("Backend is not reachable at http://localhost:8000"));
  }, []);

  async function handleBootstrap(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await createSustentraUser({ username, email, password });
      const session = await login(username, password);
      if (session.token && session.actor) {
        setSession(session.token, session.actor);
        router.push("/");
      }
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.detail : "Could not create the first user.");
    } finally {
      setBusy(false);
    }
  }

  async function handleLogin(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const session = await login(username, password);
      if (session.mfa_required && session.mfa_token) {
        setMfaToken(session.mfa_token);
        return;
      }
      if (session.token && session.actor) {
        setSession(session.token, session.actor);
        router.push("/");
      }
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.detail : "Login failed.");
    } finally {
      setBusy(false);
    }
  }

  async function handleMfa(event: FormEvent) {
    event.preventDefault();
    if (!mfaToken) return;
    setBusy(true);
    setError(null);
    try {
      const session = await completeMfaLogin(mfaToken, code);
      if (session.token && session.actor) {
        setSession(session.token, session.actor);
        router.push("/");
      }
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.detail : "MFA failed.");
    } finally {
      setBusy(false);
    }
  }

  const fieldStyle = { display: "grid", gap: 4, marginBottom: 12 };
  const inputStyle = { padding: 8, fontSize: 16 };

  if (bootstrap) {
    return (
      <section>
        <h2>Create the first Sustentra user</h2>
        <p>No database is required. This admin account is stored locally and can log in immediately.</p>
        <form onSubmit={handleBootstrap}>
          <label style={fieldStyle}>
            Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} required style={inputStyle} />
          </label>
          <label style={fieldStyle}>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required style={inputStyle} />
          </label>
          <label style={fieldStyle}>
            Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} style={inputStyle} />
          </label>
          {error ? <p style={{ color: "#a40000" }}>{error}</p> : null}
          <button type="submit" disabled={busy}>{busy ? "Creating…" : "Create user and log in"}</button>
        </form>
      </section>
    );
  }

  if (mfaToken) {
    return (
      <section>
        <h2>Multi-factor code</h2>
        <p>Enter the 6-digit app code, or a recovery code.</p>
        <form onSubmit={handleMfa}>
          <label style={fieldStyle}>
            Code
            <input value={code} onChange={(e) => setCode(e.target.value)} required style={inputStyle} />
          </label>
          {error ? <p style={{ color: "#a40000" }}>{error}</p> : null}
          <button type="submit" disabled={busy}>{busy ? "Checking…" : "Continue"}</button>
        </form>
      </section>
    );
  }

  return (
    <section>
      <h2>Log in</h2>
      <p>Sustentra users and client-users use the same login screen.</p>
      <form onSubmit={handleLogin}>
        <label style={fieldStyle}>
          Username or email
          <input value={username} onChange={(e) => setUsername(e.target.value)} required style={inputStyle} />
        </label>
        <label style={fieldStyle}>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required style={inputStyle} />
        </label>
        {error ? <p style={{ color: "#a40000" }}>{error}</p> : null}
        <button type="submit" disabled={busy}>{busy ? "Signing in…" : "Log in"}</button>
      </form>
      <p>
        <Link href="/login/reset">Forgot password</Link>
      </p>
    </section>
  );
}

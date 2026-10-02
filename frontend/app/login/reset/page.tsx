"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";

import { confirmPasswordReset, requestPasswordReset } from "../../../lib/api/auth";
import { ApiError } from "../../../lib/api/client";

export default function ResetPasswordPage() {
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleRequest(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      const result = await requestPasswordReset(email);
      setMessage(result.message);
      if (result.dev_reset_token) {
        setToken(result.dev_reset_token);
        setMessage(`${result.message} Dev reset token was filled in because there is no mailer yet.`);
      }
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.detail : "Could not request a reset.");
    }
  }

  async function handleConfirm(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await confirmPasswordReset(token, password);
      setMessage("Password updated. You can log in with the new password.");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.detail : "Could not reset the password.");
    }
  }

  const fieldStyle = { display: "grid", gap: 4, marginBottom: 12 };
  const inputStyle = { padding: 8, fontSize: 16 };

  return (
    <section>
      <h2>Reset password</h2>
      <form onSubmit={handleRequest}>
        <label style={fieldStyle}>
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required style={inputStyle} />
        </label>
        <button type="submit">Send reset token</button>
      </form>
      <form onSubmit={handleConfirm} style={{ marginTop: 24 }}>
        <label style={fieldStyle}>
          Reset token
          <input value={token} onChange={(e) => setToken(e.target.value)} required style={inputStyle} />
        </label>
        <label style={fieldStyle}>
          New password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} style={inputStyle} />
        </label>
        <button type="submit">Set new password</button>
      </form>
      {message ? <p>{message}</p> : null}
      {error ? <p style={{ color: "#a40000" }}>{error}</p> : null}
      <p>
        <Link href="/login">Back to login</Link>
      </p>
    </section>
  );
}

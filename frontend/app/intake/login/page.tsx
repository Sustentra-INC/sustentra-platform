"use client";

import { FormEvent, useState } from "react";

import { requestMagicLink } from "../../../lib/api/intake";

type Status = "idle" | "sending" | "sent" | "error";

export default function IntakeLoginPage() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setStatus("sending");
    setError(null);
    try {
      await requestMagicLink(email);
      setStatus("sent");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
      setStatus("error");
    }
  }

  if (status === "sent") {
    return (
      <section>
        <h1>Check your email</h1>
        <p className="lede">
          If <strong>{email}</strong> has an account, a sign-in link is on its way. The link
          works once and expires shortly.
        </p>
        <div className="intake-notice info">
          <p>
            Nothing arrived? Check spam, then{" "}
            <button
              type="button"
              className="intake-button link"
              onClick={() => setStatus("idle")}
            >
              try again
            </button>
            .
          </p>
        </div>
      </section>
    );
  }

  return (
    <section>
      <h1>Sign in to Sustentra</h1>
      <p className="lede">
        Enter your work email and we will send you a sign-in link. There is no password to
        remember.
      </p>

      {error ? (
        <div className="intake-notice error" role="alert">
          <p>{error}</p>
        </div>
      ) : null}

      <form onSubmit={onSubmit} className="intake-card" noValidate>
        <div className="intake-field">
          <label htmlFor="email">Work email</label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@company.com"
          />
        </div>
        <button
          type="submit"
          className="intake-button"
          disabled={status === "sending" || email.trim().length === 0}
        >
          {status === "sending" ? "Sending..." : "Email me a sign-in link"}
        </button>
      </form>
    </section>
  );
}

"use client";

import { FormEvent, useState } from "react";

import {
  BUTTON,
  BUTTON_LINK,
  CARD,
  HEADING,
  LEDE,
  NOTICE_ERROR,
  NOTICE_INFO
} from "../../../components/intake/styles";
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
      <section className="intake-enter">
        <h1 className={HEADING}>Check your email</h1>
        <p className={LEDE}>
          If <strong>{email}</strong> has an account, a sign-in link is on its way. The link
          works once and expires shortly.
        </p>
        <div className={NOTICE_INFO}>
          <p>
            Nothing arrived? Check spam, then{" "}
            <button type="button" className={BUTTON_LINK} onClick={() => setStatus("idle")}>
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
      <h1 className={HEADING}>Sign in to Sustentra</h1>
      <p className={LEDE}>We will email you a link. No password to remember.</p>

      {error ? (
        <div className={NOTICE_ERROR} role="alert">
          <p>{error}</p>
        </div>
      ) : null}

      <form onSubmit={onSubmit} className={CARD} noValidate>
        <div className="mb-[1.15rem]">
          <label htmlFor="email" className="mb-1 block font-semibold">
            Work email
          </label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@company.com"
            className="w-full rounded-md border border-line bg-surface px-3 py-2.5 focus:border-brand focus:ring-2 focus:ring-brand/25 focus:outline-none"
          />
        </div>
        <button
          type="submit"
          className={BUTTON}
          disabled={status === "sending" || email.trim().length === 0}
        >
          {status === "sending" ? "Sending..." : "Email me a sign-in link"}
        </button>
      </form>
    </section>
  );
}

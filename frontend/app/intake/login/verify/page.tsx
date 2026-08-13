"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { BUTTON, HEADING, LEDE, NOTICE_ERROR } from "../../../../components/intake/styles";
import { verifyMagicLink } from "../../../../lib/api/intake";
import type { IntakeUser } from "../../../../lib/intake-types";

type Status = "checking" | "signed_in" | "failed";

export default function IntakeVerifyPage() {
  const [status, setStatus] = useState<Status>("checking");
  const [user, setUser] = useState<IntakeUser | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Read the token from the URL directly rather than via useSearchParams, so
    // the page needs no Suspense boundary.
    const token = new URLSearchParams(window.location.search).get("token");
    if (!token) {
      setError("This link is missing its sign-in token.");
      setStatus("failed");
      return;
    }

    let cancelled = false;
    verifyMagicLink(token)
      .then((signedIn) => {
        if (cancelled) return;
        setUser(signedIn);
        setStatus("signed_in");
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setError(caught instanceof Error ? caught.message : "This link could not be used.");
        setStatus("failed");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (status === "checking") {
    return (
      <section>
        <h1 className={HEADING}>Signing you in</h1>
        <p className={LEDE}>One moment.</p>
      </section>
    );
  }

  if (status === "failed") {
    return (
      <section>
        <h1 className={HEADING}>That link did not work</h1>
        <div className={NOTICE_ERROR} role="alert">
          <p>{error}</p>
        </div>
        <p>
          Sign-in links expire and can only be used once.{" "}
          <Link href="/intake/login">Request a new one</Link>.
        </p>
      </section>
    );
  }

  return (
    <section>
      <h1 className={HEADING}>Welcome{user ? `, ${user.name}` : ""}</h1>
      <p className={LEDE}>You are signed in. Next, tell us about your company and sites.</p>
      <Link href="/intake/seed" className={`${BUTTON} inline-block no-underline`}>
        Start
      </Link>
    </section>
  );
}

"use client";

import { useEffect } from "react";

/**
 * App-wide error boundary. Mostly reached when the server could not confirm the
 * session (AUTH-007: API busy or unreachable) - the user is still signed in, so
 * offer a retry instead of sending them to login.
 */
export default function Error({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="s1-signin">
      <div className="s1-signin__card" role="alert">
        <h1 className="s1-signin__title">Something went wrong</h1>
        <p className="s1-signin__sub">We couldn&apos;t load this page. You&apos;re still signed in, so try again in a moment.</p>
        <button className="s1-signin__submit" type="button" onClick={() => retry()}>
          Try again
        </button>
      </div>
    </main>
  );
}

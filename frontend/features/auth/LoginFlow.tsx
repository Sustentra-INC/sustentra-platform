"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";

import { ApiError, login, resendOtp, verifyOtp } from "./api";
import { forgotPath, homePath, type Realm } from "./realm";
import { rememberRealm, safeNext } from "./lastRealm";
import { AuthShell } from "./AuthShell";
import styles from "./auth.module.css";

const OTP_LENGTH = 6;
const MAX_OTP_ATTEMPTS = 3;
const RESEND_SECONDS = 60;
const GENERIC_LOGIN_ERROR = "Invalid email or password.";

/** Password + email-OTP login (FE-002). Both steps live on the same route. */
export function LoginFlow({
  realm,
  next,
  onAuthenticated,
}: {
  realm: Realm;
  /** `?next=` from the URL: where to go after login, if it is a same-origin path. */
  next?: string | null;
  /** Navigate after a verified login. Defaults to a full navigation so the new
   *  session cookie is picked up by middleware and server guards. Injectable for tests. */
  onAuthenticated?: (path: string) => void;
}) {
  const [step, setStep] = useState<"password" | "otp">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  // Held in component state only — never the URL or storage.
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [otpAttempts, setOtpAttempts] = useState(0);
  const [resendIn, setResendIn] = useState(RESEND_SECONDS);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Resend countdown ticks only on the OTP step.
  useEffect(() => {
    if (step !== "otp" || resendIn <= 0) return;
    const timer = window.setTimeout(() => setResendIn((s) => s - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [step, resendIn]);

  function goToOtp(challenge: string) {
    setChallengeId(challenge);
    setCode("");
    setOtpAttempts(0);
    setResendIn(RESEND_SECONDS);
    setError(null);
    setNotice(`Enter the 6-digit code we sent to ${email}.`);
    setStep("otp");
  }

  function backToPassword(message: string) {
    setStep("password");
    setChallengeId(null);
    setCode("");
    setOtpAttempts(0);
    setPassword("");
    setNotice(null);
    setError(message);
  }

  async function onPasswordSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!email.trim() || !password) {
      setError("Enter your email and password.");
      return;
    }
    setSubmitting(true);
    try {
      const challenge = await login(realm, email.trim(), password);
      goToOtp(challenge.challenge_id);
    } catch (err) {
      setError(loginErrorMessage(err));
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  }

  async function submitOtp(value: string) {
    if (!challengeId || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await verifyOtp(challengeId, value);
      const go = onAuthenticated ?? ((path: string) => window.location.assign(path));
      rememberRealm(realm); // lets the workpaper at `/` send an ended session back here (FE-007)
      go(safeNext(next) ?? homePath(realm));
    } catch {
      const attempts = otpAttempts + 1;
      setOtpAttempts(attempts);
      setCode("");
      // Never reveal the attempt count. After the limit, restart from password.
      if (attempts >= MAX_OTP_ATTEMPTS) {
        backToPassword("That didn't work. Please sign in again.");
      } else {
        setError("That code is incorrect. Check it and try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  function onCodeChange(raw: string) {
    const digits = raw.replace(/\D/g, "").slice(0, OTP_LENGTH);
    setCode(digits);
    if (digits.length === OTP_LENGTH) void submitOtp(digits);
  }

  async function onResend() {
    if (!challengeId || resendIn > 0) return;
    setError(null);
    try {
      await resendOtp(challengeId);
      setResendIn(RESEND_SECONDS);
      setNotice("A new code is on its way.");
    } catch {
      setError("Could not resend the code. Try again in a moment.");
    }
  }

  if (step === "otp") {
    return (
      <AuthShell title="Check your email" subtitle={notice ?? undefined}>
        <form className={styles.form} onSubmit={(e) => e.preventDefault()}>
          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}
          <div className={styles.field}>
            <label className={styles.label} htmlFor="otp">
              6-digit code
            </label>
            <input
              id="otp"
              className={styles.otp}
              value={code}
              onChange={(e) => onCodeChange(e.target.value)}
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              maxLength={OTP_LENGTH}
              disabled={submitting}
            />
          </div>
          <div className={styles.row}>
            <button type="button" className={styles.link} onClick={onResend} disabled={resendIn > 0}>
              {resendIn > 0 ? `Resend code in ${resendIn}s` : "Resend code"}
            </button>
            <button type="button" className={styles.link} onClick={() => backToPassword("")}>
              Use a different account
            </button>
          </div>
        </form>
      </AuthShell>
    );
  }

  return (
    <AuthShell title="Sign in" subtitle={notice ?? undefined}>
      <form className={styles.form} onSubmit={onPasswordSubmit} noValidate>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
        <div className={styles.field}>
          <label className={styles.label} htmlFor="email">
            Email
          </label>
          <input
            id="email"
            className={styles.input}
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            autoFocus
          />
        </div>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="password">
            Password
          </label>
          <div className={styles.inputWrap}>
            <input
              id="password"
              className={styles.input}
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
            <button
              type="button"
              className={styles.reveal}
              onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>
        </div>
        <button type="submit" className={styles.button} disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
        <Link className={styles.link} href={forgotPath(realm)}>
          Forgot password?
        </Link>
      </form>
    </AuthShell>
  );
}

function loginErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.status === 429) {
    const minutes = err.retryAfter ? Math.ceil(err.retryAfter / 60) : null;
    return minutes
      ? `Too many attempts. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`
      : "Too many attempts. Try again later.";
  }
  // All 401s (and anything else) stay generic — never reveal which field was wrong.
  return GENERIC_LOGIN_ERROR;
}

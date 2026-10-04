import { api, ApiError } from "../../lib/api";
import { realmBody, type Realm } from "./realm";

/**
 * MVP auth API (FE-002). Thin wrappers over the `/api/v1/auth/*` endpoints, using
 * the same-origin cookie client (`lib/api.ts`). The backend (AUTH-005 / AUTH-006)
 * is not built yet — these are the agreed contracts; adjust the paths/shapes here
 * if they land differently. The 6-digit OTP flow is: login → challenge → verify.
 */

export interface LoginChallenge {
  /** Opaque id for the in-flight OTP challenge. Held in component state only. */
  challenge_id: string;
}

/** Step 1 — email + password. On success the API emails a 6-digit OTP. */
export function login(realm: Realm, email: string, password: string): Promise<LoginChallenge> {
  return api<LoginChallenge>("/auth/login", {
    method: "POST",
    body: { email, password, ...realmBody(realm) },
  });
}

/** Step 2 — verify the OTP. On success the API sets the `__Host-session` cookie (204). */
export function verifyOtp(challengeId: string, code: string): Promise<void> {
  return api<void>("/auth/login/verify", {
    method: "POST",
    body: { challenge_id: challengeId, code },
  });
}

/** Resend the OTP for an in-flight challenge. */
export function resendOtp(challengeId: string): Promise<void> {
  return api<void>("/auth/login/resend", {
    method: "POST",
    body: { challenge_id: challengeId },
  });
}

/** Always resolves, whether or not the email exists (neutral by design). */
export function requestPasswordReset(realm: Realm, email: string): Promise<void> {
  return api<void>("/auth/password/forgot", {
    method: "POST",
    body: { email, ...realmBody(realm) },
  });
}

/** Set a new password with a reset token. 400 if the token is invalid/expired/used. */
export function resetPassword(token: string, password: string): Promise<void> {
  return api<void>("/auth/password/reset", {
    method: "POST",
    body: { token, password },
  });
}

export interface InviteDetails {
  org_name: string;
  org_slug: string;
  email: string;
  first_name: string;
  last_name: string;
}

/** Validate an invite token on page load. 400 if invalid/expired/used (generic). */
export function validateInvite(token: string): Promise<InviteDetails> {
  return api<InviteDetails>(`/auth/invite/validate?token=${encodeURIComponent(token)}`);
}

/** Accept an invite — sets the password and activates the user. Does NOT create a
 *  session; the user then logs in normally. 400 if the token is invalid. */
export function acceptInvite(token: string, password: string): Promise<void> {
  return api<void>("/auth/invite/accept", {
    method: "POST",
    body: { token, password },
  });
}

export { ApiError };

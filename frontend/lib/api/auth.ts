import { apiRequest } from "./client";
import type { Actor } from "../session";

export interface AuthStatus {
  bootstrap_required: boolean;
  persistence: string;
  sustentra_user_count: number;
  client_count: number;
}

export interface LoginResponse {
  mfa_required: boolean;
  token?: string;
  mfa_token?: string;
  expires_at?: string;
  actor_type?: Actor["actor_type"];
  actor?: Actor;
}

export function getAuthStatus() {
  return apiRequest<AuthStatus>("/v1/auth/status");
}

export function login(username: string, password: string) {
  return apiRequest<LoginResponse>("/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password })
  });
}

export function completeMfaLogin(mfaToken: string, code: string) {
  return apiRequest<LoginResponse>("/v1/auth/login/mfa", {
    method: "POST",
    body: JSON.stringify({ mfa_token: mfaToken, code })
  });
}

export function logout() {
  return apiRequest<{ status: string }>("/v1/auth/logout", { method: "POST" });
}

export function getMe() {
  return apiRequest<Actor>("/v1/auth/me");
}

export function requestPasswordReset(email: string) {
  return apiRequest<{ status: string; message: string; dev_reset_token?: string }>(
    "/v1/auth/password-reset/request",
    { method: "POST", body: JSON.stringify({ email }) }
  );
}

export function confirmPasswordReset(token: string, newPassword: string) {
  return apiRequest<{ status: string }>("/v1/auth/password-reset/confirm", {
    method: "POST",
    body: JSON.stringify({ token, new_password: newPassword })
  });
}

export function setupMfa() {
  return apiRequest<{
    mfa_enabled: boolean;
    secret: string;
    otpauth_uri: string;
    dev_current_code?: string | null;
  }>("/v1/auth/mfa/setup", { method: "POST" });
}

export function confirmMfa(code: string) {
  return apiRequest<{ mfa_enabled: boolean; recovery_codes: string[] }>(
    "/v1/auth/mfa/confirm",
    { method: "POST", body: JSON.stringify({ code }) }
  );
}

export function disableMfa(password: string, code: string) {
  return apiRequest<{ mfa_enabled: boolean }>("/v1/auth/mfa/disable", {
    method: "POST",
    body: JSON.stringify({ password, code })
  });
}

export function createSustentraUser(payload: {
  username: string;
  email: string;
  password: string;
  role?: string;
}) {
  return apiRequest("/v1/users", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function listSustentraUsers() {
  return apiRequest<Actor[]>("/v1/users");
}

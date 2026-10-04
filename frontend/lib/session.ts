const TOKEN_KEY = "sustentra_token";
export const ACTOR_KEY = "sustentra_actor";
/** Fired on this tab when the session changes (the `storage` event only fires in other tabs). */
export const SESSION_CHANGE_EVENT = "sustentra:session-change";

export interface Actor {
  actor_id: string;
  actor_type: "sustentra_user" | "client_user";
  username: string;
  email: string;
  role?: string;
  client_id?: string;
  mfa_enabled?: boolean;
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getActor(): Actor | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(ACTOR_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Actor;
  } catch {
    return null;
  }
}

export function setSession(token: string, actor: Actor): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(ACTOR_KEY, JSON.stringify(actor));
  window.dispatchEvent(new Event(SESSION_CHANGE_EVENT));
}

export function clearSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(ACTOR_KEY);
  window.dispatchEvent(new Event(SESSION_CHANGE_EVENT));
}

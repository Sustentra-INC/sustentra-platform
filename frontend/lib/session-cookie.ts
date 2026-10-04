/**
 * Name of the session cookie the API sets on login. `__Host-` locks it to the
 * exact host over HTTPS with Path=/ and no Domain — the hardened default.
 * Shared by the edge middleware and the server-side auth guard.
 */
export const SESSION_COOKIE = "__Host-session";

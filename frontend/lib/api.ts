/**
 * MVP API client (FE-001). One same-origin fetch wrapper for the production
 * auth/tenancy app. Requests go to `/api/v1/*`, which `next.config` rewrites to
 * the backend in dev and Caddy routes in prod. Auth rides on the `__Host-session`
 * cookie via `credentials: "same-origin"` — no bearer tokens, no CORS.
 *
 * The S1 workpaper seam (`features/s1/api`) uses it too (FE-007): every S1 route
 * needs the session cookie and is scoped to the caller's org (SEC-001).
 */

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly body: unknown;
  /** Seconds to wait before retrying, from a `Retry-After` header (lockouts). */
  readonly retryAfter: number | null;

  constructor(status: number, detail: string, body: unknown, retryAfter: number | null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.body = body;
    this.retryAfter = retryAfter;
  }
}

export interface ApiOptions extends Omit<RequestInit, "body"> {
  /** JSON-serializable body, or a FormData for multipart uploads. */
  body?: unknown;
}

/** Same-origin URL for an API path, e.g. for a download link or a preview iframe. */
export function apiPath(path: string): string {
  return `/api/v1${path}`;
}

export async function api<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const { body, headers: headersInit, ...rest } = options;
  const headers = new Headers(headersInit);
  headers.set("Accept", "application/json");

  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body; // let the browser set the multipart boundary
  } else if (body !== undefined) {
    payload = JSON.stringify(body);
    if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  }

  const response = await fetch(apiPath(path), {
    ...rest,
    headers,
    body: payload,
    credentials: "same-origin",
    cache: "no-store",
  });

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    let parsed: unknown;
    try {
      parsed = await response.json();
      if (parsed && typeof parsed === "object" && "detail" in parsed) {
        const d = (parsed as { detail: unknown }).detail;
        if (typeof d === "string") detail = d;
        else if (Array.isArray(d)) detail = d.join(", ");
      }
    } catch {
      // Non-JSON error body — keep the status-only message.
    }
    const retryHeader = response.headers.get("Retry-After");
    const retryAfter = retryHeader ? Number(retryHeader) : null;
    throw new ApiError(response.status, detail, parsed, Number.isFinite(retryAfter) ? retryAfter : null);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Like `api`, but a 404 resolves to `null` (the resource does not exist yet, or
 *  belongs to another org). Every other failure still throws `ApiError`. */
export async function apiMaybe<T>(path: string, options: ApiOptions = {}): Promise<T | null> {
  try {
    return await api<T>(path, options);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

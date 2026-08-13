import {
  AnswerResult,
  FieldError,
  IntakeUser,
  InterviewStep,
  NotSureResult,
  ParseResponse,
  SeedFormAnswers,
  SeedFormError,
  SeedFormSchema,
  SeedFormSubmitResult
} from "../intake-types";

const API_BASE =
  process.env.NEXT_PUBLIC_BACKEND_API_URL ?? "http://localhost:8000";

const SESSION_KEY = "sustentra.intake.session";

/**
 * Session token storage.
 *
 * Pilot-grade: the token lives in localStorage so the flow works without cookie
 * or CSRF plumbing. An httpOnly cookie set by the backend is the right answer
 * before this is exposed to real clients.
 */
export function getSessionToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(SESSION_KEY);
}

export function setSessionToken(token: string): void {
  window.localStorage.setItem(SESSION_KEY, token);
}

export function clearSessionToken(): void {
  window.localStorage.removeItem(SESSION_KEY);
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  auth?: boolean;
}

export async function intakeRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, auth = true } = options;
  const headers: Record<string, string> = { "Content-Type": "application/json" };

  if (auth) {
    const token = getSessionToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store"
  });

  if (response.ok) {
    return (await response.json()) as T;
  }

  let detail: unknown;
  try {
    detail = (await response.json())?.detail;
  } catch {
    detail = undefined;
  }

  // The seed-form endpoint returns {detail: {errors: [...]}} so the form can
  // show every problem at once instead of one at a time.
  if (detail && typeof detail === "object" && Array.isArray((detail as { errors?: FieldError[] }).errors)) {
    throw new SeedFormError((detail as { errors: FieldError[] }).errors);
  }

  if (response.status === 401) {
    clearSessionToken();
  }

  throw new Error(typeof detail === "string" ? detail : `Request failed (${response.status})`);
}

export function requestMagicLink(email: string): Promise<{ status: string }> {
  return intakeRequest("/v1/intake/auth/magic-link", {
    method: "POST",
    body: { email },
    auth: false
  });
}

export async function verifyMagicLink(token: string): Promise<IntakeUser> {
  const result = await intakeRequest<{ session_token: string; user: IntakeUser }>(
    "/v1/intake/auth/verify",
    { method: "POST", body: { token }, auth: false }
  );
  setSessionToken(result.session_token);
  return result.user;
}

export function getCurrentUser(): Promise<IntakeUser> {
  return intakeRequest<IntakeUser>("/v1/intake/auth/me");
}

export function signOut(): Promise<{ status: string }> {
  const promise = intakeRequest<{ status: string }>("/v1/intake/auth/sign-out", {
    method: "POST"
  });
  clearSessionToken();
  return promise;
}

export function getSeedFormSchema(overlayId?: string): Promise<SeedFormSchema> {
  const query = overlayId ? `?overlay_id=${encodeURIComponent(overlayId)}` : "";
  return intakeRequest<SeedFormSchema>(`/v1/intake/seed-form/schema${query}`);
}

export function submitSeedForm(payload: {
  company: Record<string, unknown>;
  sites: Array<Record<string, unknown>>;
}): Promise<SeedFormSubmitResult> {
  return intakeRequest<SeedFormSubmitResult>("/v1/intake/seed-form", {
    method: "POST",
    body: payload
  });
}

export function getSeedFormAnswers(): Promise<SeedFormAnswers> {
  return intakeRequest<SeedFormAnswers>("/v1/intake/seed-form/answers");
}

export function startInterview(): Promise<InterviewStep & { summary: unknown }> {
  return intakeRequest("/v1/intake/interview/start", { method: "POST" });
}

export function getNextQuestion(): Promise<InterviewStep> {
  return intakeRequest<InterviewStep>("/v1/intake/interview/next");
}

export function submitAnswer(payload: {
  datapoint_id: string;
  scope_ref: string | null;
  answer: Record<string, unknown>;
  ai_assisted?: boolean;
}): Promise<AnswerResult> {
  return intakeRequest<AnswerResult>("/v1/intake/interview/answer", {
    method: "POST",
    body: payload
  });
}

export function sayNotSure(payload: {
  datapoint_id: string;
  scope_ref: string | null;
}): Promise<NotSureResult> {
  return intakeRequest<NotSureResult>("/v1/intake/interview/not-sure", {
    method: "POST",
    body: payload
  });
}

export function parseFreeText(payload: {
  datapoint_id: string;
  scope_ref: string | null;
  text: string;
}): Promise<ParseResponse> {
  return intakeRequest<ParseResponse>("/v1/intake/interview/parse", {
    method: "POST",
    body: payload
  });
}

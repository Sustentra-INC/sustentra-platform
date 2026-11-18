import { api, ApiError } from "../../../lib/api";
import type { AskDraft } from "../requests/requestsStore";
import type { Ask, AskOrigin, RequestType } from "../types/requests";
import { workpaperKey } from "./workpaper";
import type { WorkpaperItem } from "./workpaper";

/**
 * Evidence requests change only through these actions (MVP-86): create, edit, send,
 * resolve and withdraw. The server checks the request's state, numbers sent requests
 * and records the signed-in user as the person who acted, so none of these bodies
 * carries a name, a login, a state, a number or a history.
 */

export type RequestAction = "create" | "edit" | "send" | "resolve" | "withdraw";

/** A failed request action. `status` is null when no answer came back. */
export class RequestActionError extends Error {
  constructor(message: string, readonly status: number | null) {
    super(message);
    this.name = "RequestActionError";
  }
}

export interface CreateRequestBody {
  id: string;
  type: RequestType;
  whatIsNeeded: string;
  source: {
    origin: AskOrigin;
    documentId: string | null;
    fieldKey: string | null;
    itemLabel: string;
    facilityName: string | null;
    period: string | null;
    sourcePage: number | null;
    arrival: string | null;
  };
  linkedFromAskId: string | null;
}

export interface SentRequest {
  requestNumber: number;
  sentAt: string;
  askIds: string[];
  asks: Ask[];
}

// The server's limits (api/requests.py). It forbids extra fields and refuses longer text.
const LABEL_MAX = 300;
const SHORT_MAX = 300;
const REF_MAX = 500;
const UNNAMED_ITEM = "Unnamed item";

/** The first `max` characters, counted as the server counts them (code points). */
function cut(text: string, max: number): string {
  const chars = Array.from(text);
  return chars.length > max ? chars.slice(0, max).join("") : text;
}

function itemLabel(raw: string): string {
  const label = raw.trim();
  if (!label) return UNNAMED_ITEM;
  const chars = Array.from(label);
  return chars.length > LABEL_MAX ? `${chars.slice(0, LABEL_MAX - 1).join("")}…` : label;
}

function shortText(raw: string | null | undefined): string | null {
  const text = (raw ?? "").trim();
  return text ? cut(text, SHORT_MAX) : null;
}

function reference(raw: string | null | undefined): string | null {
  return raw && Array.from(raw).length <= REF_MAX ? raw : null;
}

/** The create body for a draft: only what a person writes. The draft's raisedByName and
 *  raisedByLogin stay on the browser; the server takes the actor from the session. */
export function requestBodyFromDraft(id: string, draft: AskDraft): CreateRequestBody {
  const page = draft.sourcePage;
  return {
    id,
    type: draft.type,
    whatIsNeeded: draft.whatIsNeeded.trim(),
    source: {
      origin: draft.origin ?? "workspace_document",
      documentId: reference(draft.documentId),
      fieldKey: reference(draft.fieldKey),
      itemLabel: itemLabel(draft.itemLabel),
      facilityName: shortText(draft.facilityName),
      period: shortText(draft.period),
      sourcePage: typeof page === "number" && Number.isFinite(page) && page >= 1 ? Math.floor(page) : null,
      arrival: shortText(draft.arrival),
    },
    linkedFromAskId: draft.linkedFromAskId ?? null,
  };
}

const base = (engagementId: string) => `/engagements/${encodeURIComponent(engagementId)}`;
const one = (engagementId: string, askId: string) =>
  `${base(engagementId)}/requests/${encodeURIComponent(workpaperKey(askId))}`;

// Each action takes an optional `signal`, so a caller can stop waiting for an answer that never comes.

/** Raise a request (201). It starts not yet sent, raised by the signed-in user. */
export function createRequest(engagementId: string, body: CreateRequestBody, signal?: AbortSignal): Promise<Ask> {
  return api<Ask>(`${base(engagementId)}/requests`, { method: "POST", body, signal });
}

/** Change a request's text while it is not yet sent. */
export function editRequest(
  engagementId: string,
  askId: string,
  whatIsNeeded: string,
  signal?: AbortSignal
): Promise<Ask> {
  return api<Ask>(one(engagementId, askId), { method: "PATCH", body: { whatIsNeeded }, signal });
}

/** Send requests together as one numbered request. `lineNumbers` lets several lines
 *  share a line number; it is left out when there is none. */
export function sendRequests(
  engagementId: string,
  askIds: string[],
  lineNumbers?: Record<string, number>,
  signal?: AbortSignal
): Promise<SentRequest> {
  const body: { askIds: string[]; lineNumbers?: Record<string, number> } = { askIds };
  if (lineNumbers && Object.keys(lineNumbers).length > 0) body.lineNumbers = lineNumbers;
  return api<SentRequest>(`${base(engagementId)}/requests/send`, { method: "POST", body, signal });
}

export function resolveRequest(
  engagementId: string,
  askId: string,
  resolution?: { link?: string | null; note?: string | null },
  signal?: AbortSignal
): Promise<Ask> {
  return api<Ask>(`${one(engagementId, askId)}/resolve`, {
    method: "POST",
    body: { link: resolution?.link || null, note: resolution?.note || null },
    signal,
  });
}

export function withdrawRequest(
  engagementId: string,
  askId: string,
  reason: string,
  signal?: AbortSignal
): Promise<Ask> {
  return api<Ask>(`${one(engagementId, askId)}/withdraw`, { method: "POST", body: { reason }, signal });
}

/** The engagement's requests, as the server stores them. */
export async function loadAsks(engagementId: string, signal?: AbortSignal): Promise<Ask[]> {
  const { items } = await api<{ items: WorkpaperItem[] }>(`${base(engagementId)}/workpaper-items?kind=ask`, {
    signal,
  });
  return items.map((item) => item.payload as unknown as Ask);
}

// --- Messages ---------------------------------------------------------------------

/** What did not happen, for "Something went wrong on our side, so …". */
const NOUN: Record<RequestAction, string> = {
  create: "the request wasn't added",
  edit: "the text wasn't saved",
  send: "the requests weren't marked sent",
  resolve: "the request wasn't resolved",
  withdraw: "the request wasn't withdrawn",
};

const ARCHIVED_DETAIL = "Engagement is archived.";
const DUPLICATE_DETAIL = "A request with this id already exists.";
const REQUEST_NOT_FOUND_DETAIL = "Request not found.";

const ARCHIVED = "This engagement is archived, so its requests can't change.";
const ALREADY_ADDED = "This request was already added. The list now shows it.";
const REQUEST_GONE = "This request is no longer in this engagement. The list now shows the current requests.";
const NOT_ALLOWED = "Your role can view requests but not change them.";
/** What the person reads when the session has ended. */
export const SESSION_ENDED = "Your session ended. Sign in again to continue.";
const NOT_VALID =
  "This change couldn't be saved because some of its details aren't valid. Reload the page and try again.";
const NOT_SAVED = "The change wasn't saved. Check your connection and try again.";

/** What the server refused, by the name of the field in the 422 body. */
const FIELD_MESSAGE: Record<string, string> = {
  whatIsNeeded: "Write what is needed, in up to 2,000 characters.",
  reason: "Give a reason for withdrawing, in up to 1,000 characters.",
  link: "Keep the link and the note under 2,000 characters each.",
  note: "Keep the link and the note under 2,000 characters each.",
  itemLabel: "The item's name is too long to save. Shorten it and try again.",
};
const TOO_MANY = "Send at most 200 requests at once.";

/** `api` makes up this text when the answer has no detail of its own. */
const STATUS_ONLY = /^Request failed \(\d+\)$/;

/** The detail in the error's body: a string, a FastAPI validation list, or undefined. */
function bodyDetail(error: ApiError): unknown {
  const body = error.body;
  return body && typeof body === "object" && "detail" in body ? (body as { detail: unknown }).detail : undefined;
}

/** The sentence the server sent, or null when it sent none (or only a validation list). */
function serverSentence(error: ApiError): string | null {
  const detail = bodyDetail(error);
  if (typeof detail === "string") return detail.trim() ? detail : null;
  if (detail !== undefined) return null;
  return error.detail && !STATUS_ONLY.test(error.detail) ? error.detail : null;
}

const isSentence = (text: string) => /[.!?]$/.test(text.trim());

/** The message for the first field error in a 422 list that we can name. */
function validationMessage(error: ApiError): string {
  const list = bodyDetail(error);
  if (!Array.isArray(list)) return NOT_VALID;
  for (const item of list) {
    if (!item || typeof item !== "object") continue;
    const { loc, type } = item as { loc?: unknown; type?: unknown };
    const field = Array.isArray(loc) ? loc[loc.length - 1] : undefined;
    if (field === "askIds") {
      // The same field also fails for an empty list and for a repeated id.
      if (type === "too_long") return TOO_MANY;
    } else if (typeof field === "string" && Object.hasOwn(FIELD_MESSAGE, field)) {
      return FIELD_MESSAGE[field];
    }
  }
  return NOT_VALID;
}

/**
 * The sentence to show when a request action fails: what went wrong and what to do.
 * It reads the status and detail of an `ApiError`; anything else is a lost connection.
 */
export function requestActionMessage(error: unknown, action: RequestAction): string {
  if (!(error instanceof ApiError)) return NOT_SAVED;
  const { status } = error;
  const sentence = serverSentence(error);

  if (status >= 500) {
    return `Something went wrong on our side, so ${NOUN[action]}. Try again; if it happens again, tell us.`;
  }
  if (status === 401) return SESSION_ENDED;
  if (status === 403) return NOT_ALLOWED;
  if (status === 409) {
    if (sentence === ARCHIVED_DETAIL) return ARCHIVED;
    if (sentence === DUPLICATE_DETAIL) return ALREADY_ADDED;
    return sentence ?? NOT_VALID;
  }
  if (status === 404) {
    // The send endpoint names the request it could not find; the others answer "Request not found."
    if (sentence && sentence !== REQUEST_NOT_FOUND_DETAIL && isSentence(sentence)) return sentence;
    return REQUEST_GONE;
  }
  if (status === 422) return sentence ?? validationMessage(error);
  // Any other answer (400, 405, 413, 429 ...): the server replied, so the connection is not the
  // problem, and the change did not go through as sent.
  return status >= 400 ? NOT_VALID : NOT_SAVED;
}

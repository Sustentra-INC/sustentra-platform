/**
 * The ask / request model shared by Evidence Workspace, Extraction Review and
 * Evidence Requests (screen 4). Every write goes through one persist function
 * (see `features/s1/requests/requestsStore.ts`) so the backend swap is a single
 * change. There is no backend for these objects yet — fixture mode only.
 */

export type RequestType =
  | "missing_document"
  | "replace_document"
  | "missing_data"
  | "clarify"
  | "confirm_or_restate";

export const REQUEST_TYPES: ReadonlyArray<{ value: RequestType; label: string }> = [
  { value: "missing_document", label: "Missing document" },
  { value: "replace_document", label: "Replace document" },
  { value: "missing_data", label: "Missing data" },
  { value: "clarify", label: "Clarify" },
  { value: "confirm_or_restate", label: "Confirm or restate" },
];

/** Where an ask was raised. Enough to render the Item cell and link back. */
export type AskOrigin = "workspace_document" | "review_value" | "expected_item" | "data_point";

export interface AskSource {
  origin: AskOrigin;
  /** Document the ask hangs off, when there is one. */
  documentId?: string | null;
  /** Value/field the ask hangs off, on Extraction Review. */
  fieldKey?: string | null;
  /** Human label of the item, as it read on the source page. */
  itemLabel: string;
  facilityName: string | null;
  period: string | null;
  /** For a value ask: the source page, so Evidence requests can reopen it there. */
  sourcePage?: number | null;
  /** How the raised-from item arrived (for the modal header line). */
  arrival?: string | null;
}

export type AskState = "not_yet_sent" | "requested" | "resolved" | "withdrawn";

export interface AskEvent {
  kind: "raised" | "edited" | "sent" | "resolved" | "withdrawn";
  actorName: string;
  actorLogin: string;
  at: string;
  detail?: string;
}

export interface Ask {
  id: string;
  type: RequestType;
  /** The "what is needed" text; editable on Evidence requests until sent. */
  whatIsNeeded: string;
  source: AskSource;
  raisedByName: string;
  raisedByLogin: string;
  raisedAt: string;
  state: AskState;
  /** Set when sent, as part of a request. An ask belongs to one request only. */
  requestNumber: number | null;
  lineNumber: number | null;
  /** A problem that came back: this ask links to the old (resolved) one. */
  linkedFromAskId?: string | null;
  resolution?: {
    at: string;
    by: string;
    link?: string | null;
    note?: string | null;
  } | null;
  withdrawReason?: string | null;
  history: AskEvent[];
}

/** A sent request bundles asks into one email. Created at "mark as sent". */
export interface ClientRequest {
  requestNumber: number;
  sentAt: string;
  askIds: string[];
}

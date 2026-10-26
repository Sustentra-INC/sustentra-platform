import type { SourceAnchor } from "../utils/sourceAnchor";
import type { RequestType } from "./requests";

/** Scope placement of a value. Line 2 of a card never goes blank. */
export type ScopePlacement = "general" | "scope1" | "scope2_location" | "scope2_market" | "not_placed";

export type ValueReviewState = "to_review" | "accepted" | "corrected" | "requested";

export type SourceKind = "pdf" | "image" | "spreadsheet" | "text";

export interface ValueRecordEntry {
  kind: "machine" | "human";
  actor: string;
  at: string;
  action: string;
  reason?: string;
  /** The ask this entry added the value to, so the card can say whether it was sent. */
  askId?: string;
}

/** A value drawn on its document in the source pane: clicking it selects the value. A PDF
 *  or image value has a box on its page (`span`); a workbook, CSV or Word value has a cell,
 *  row or line (`anchor`) and the text it was read as (`rawText`). */
export interface PageMark {
  id: string;
  span: ReviewSpan | null;
  anchor?: SourceAnchor | null;
  rawText?: string | null;
  /** What the value is, for the box's tooltip and screen readers. */
  label: string;
  reviewState: ValueReviewState;
}

/** Normalized 0..1 rectangle over the rendered page — ready for real geometry. */
export interface ReviewSpan {
  page: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ReviewValue {
  id: string;
  documentId: string;
  filename: string;
  documentType: string;

  // navigator placement
  facilityId: string | null;
  entityLevel?: boolean;
  notYetKnown?: boolean;
  /** Workbook section, used as the navigator child in place of a type. */
  section?: "general" | "scope1" | "scope2";

  // card content
  period: string;
  whatItIs: string;
  scope: ScopePlacement;
  value: string;
  unit: string;
  /**
   * The methodology field this value maps to — the id the backend's
   * MethodologyValue keys off. Accept carries it through so the S1->S2 handoff
   * is not a retrofit. Placeholder until the real field list arrives.
   */
  methodologyFieldId?: string;

  // review
  reviewState: ValueReviewState;
  /** When corrected, the machine value stays visible beside the change. */
  originalValue?: string | null;
  record: ValueRecordEntry[];
  requestPreselect?: RequestType;
  /** The document was withdrawn while open: cards grey, actions disabled. */
  withdrawn?: boolean;
  withdrawnReason?: string;

  // source
  sourceKind: SourceKind;
  page: number;
  pageCount: number;
  /** null → the extractor gave no span; show the snippet and say so. */
  span?: ReviewSpan | null;
  snippet?: string | null;
  sheet?: string | null;
  cell?: string | null;
  /** Workbook, CSV, Word: the cell, row or line the value was read from. */
  anchor?: SourceAnchor | null;
  /** The text as read on the document ("96,000"), to find it within its row or line. */
  rawText?: string | null;
  /** Demo documents: where on the drawn page a reviewer highlighted this value. */
  docAnchor?: string;
  /** Backend values only: the candidate a review decision is recorded against. */
  reviewToken?: string;
  /** The extractor did not find this value on the document; the reviewer can enter it. */
  missing?: boolean;
}

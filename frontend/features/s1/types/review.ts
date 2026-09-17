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
}

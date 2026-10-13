import type { FieldState, ReviewStatus, ValueProperty } from "./states";

export interface SourceLocationPage {
  kind: "page";
  page: number;
  region: { x: number; y: number; w: number; h: number } | null;
}

export interface SourceLocationCells {
  kind: "cells";
  sheet: string;
  range: string;
}

export type SourceLocation = SourceLocationPage | SourceLocationCells;

export interface ExtractedField {
  documentId: string;
  canonicalTypeId: string | null;
  fieldKey: string;
  reviewToken?: string;
  fieldLabel: string;
  value: string | null;
  unit: string | null;
  valueProperties: ValueProperty[];
  fieldState: FieldState;
  snippet: string | null;
  snippetContext: string | null;
  location: SourceLocation | null;
  reviewStatus: ReviewStatus;
  correctedValue: string | null;
  /** The unit the reviewer set when correcting, if they changed it. */
  correctedUnit?: string | null;
  /** Who made the latest review decision, and when (from the API). */
  reviewedBy?: string | null;
  reviewedAt?: string | null;
  valueOrigin: "extracted" | "computed" | "verifier_determined" | "assigned";
}

export interface ReviewQueueItem {
  documentId: string;
  filename: string;
  facility: string;
  period: string;
  reviewedCount: number;
  fieldCount: number;
}

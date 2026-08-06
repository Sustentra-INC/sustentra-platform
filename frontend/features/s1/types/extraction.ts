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
  canonicalTypeId: string;
  fieldKey: string;
  candidateSnapshot?: Record<string, unknown>;
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

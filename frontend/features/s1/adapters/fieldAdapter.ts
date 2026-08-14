import type { ExtractedField, ValueProperty } from "../types";
import { resolveFieldKey } from "../utils/resolveFieldKey";

export interface BackendExtractionCandidateLike {
  candidate_id?: string;
  evidence_id?: string;
  document_id: string;
  field_name: string;
  display_label: string;
  raw_value?: string | number | boolean | null;
  normalized_value: string | number | boolean | null;
  unit: string | null;
  confidence?: number | null;
  validation_flags?: string[] | null;
  source_reference?: {
    text_snippet?: string | null;
    page_number?: number | null;
    sheet_name?: string | null;
    cell_or_range?: string | null;
    bounding_box?: { x?: number; y?: number; w?: number; h?: number } | null;
  } | null;
}

export function mapBackendCandidateToExtractedField(
  candidate: BackendExtractionCandidateLike,
  canonicalTypeId: string | null
): ExtractedField {
  const value =
    candidate.normalized_value === null || candidate.normalized_value === undefined
      ? null
      : String(candidate.normalized_value);

  return {
    documentId: candidate.document_id,
    canonicalTypeId,
    fieldKey: resolveFieldKey({
      candidateId: candidate.candidate_id,
      documentId: candidate.document_id,
      backendFieldId: candidate.field_name,
    }),
    reviewToken: encodeReviewCandidateToken(candidate),
    fieldLabel: candidate.display_label,
    value,
    unit: candidate.unit,
    valueProperties: mapValidationFlags(candidate.validation_flags),
    fieldState: value === null ? "missing_requestable" : "populated",
    snippet: candidate.source_reference?.text_snippet ?? null,
    snippetContext: candidate.source_reference?.text_snippet ?? null,
    location:
      typeof candidate.source_reference?.page_number === "number"
        ? {
            kind: "page",
            page: candidate.source_reference.page_number,
            region: candidate.source_reference.bounding_box
              ? {
                  x: Number(candidate.source_reference.bounding_box.x ?? 0),
                  y: Number(candidate.source_reference.bounding_box.y ?? 0),
                  w: Number(candidate.source_reference.bounding_box.w ?? 0),
                  h: Number(candidate.source_reference.bounding_box.h ?? 0),
                }
              : null,
          }
        : candidate.source_reference?.sheet_name && candidate.source_reference?.cell_or_range
          ? {
              kind: "cells",
              sheet: candidate.source_reference.sheet_name,
              range: candidate.source_reference.cell_or_range,
            }
          : null,
    reviewStatus: "unreviewed",
    correctedValue: null,
    valueOrigin: "extracted",
  };
}

export function encodeReviewCandidateToken(candidate: BackendExtractionCandidateLike): string {
  const payload = JSON.stringify({
    candidate_id: candidate.candidate_id,
    evidence_id: candidate.evidence_id,
    document_id: candidate.document_id,
    field_name: candidate.field_name,
    display_label: candidate.display_label,
    raw_value: candidate.raw_value ?? candidate.normalized_value,
    normalized_value: candidate.normalized_value,
    unit: candidate.unit,
    confidence: candidate.confidence ?? null,
    source_reference: candidate.source_reference ?? null,
    validation_flags: candidate.validation_flags ?? [],
  });
  if (typeof btoa === "function") return btoa(payload);
  return Buffer.from(payload, "utf8").toString("base64");
}

export function decodeReviewCandidateToken(token: string): BackendExtractionCandidateLike | null {
  try {
    const payload = typeof atob === "function" ? atob(token) : Buffer.from(token, "base64").toString("utf8");
    return JSON.parse(payload) as BackendExtractionCandidateLike;
  } catch {
    return null;
  }
}

function mapValidationFlags(flags?: string[] | null): ValueProperty[] {
  const allowed: ValueProperty[] = ["estimated_read", "unit_missing", "unit_ambiguous", "format_mismatch"];
  return (flags ?? []).filter((flag): flag is ValueProperty =>
    allowed.includes(flag as ValueProperty)
  );
}

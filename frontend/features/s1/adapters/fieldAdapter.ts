import type { ExtractedField } from "../types";
import { resolveFieldKey } from "../utils/resolveFieldKey";

export interface BackendExtractionCandidateLike {
  candidate_id?: string;
  evidence_id?: string;
  document_id: string;
  field_name: string;
  display_label: string;
  normalized_value: string | number | boolean | null;
  unit: string | null;
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
  canonicalTypeId: string
): ExtractedField {
  const value =
    candidate.normalized_value === null || candidate.normalized_value === undefined
      ? null
      : String(candidate.normalized_value);

  return {
    documentId: candidate.document_id,
    canonicalTypeId,
    fieldKey: resolveFieldKey({
      canonicalTypeId,
      backendFieldId: candidate.field_name,
    }),
    candidateSnapshot: { ...candidate },
    fieldLabel: candidate.display_label,
    value,
    unit: candidate.unit,
    valueProperties: candidate.unit ? [] : value === null ? [] : ["unit_missing"],
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

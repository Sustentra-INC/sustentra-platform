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
  source_reference?: { text_snippet?: string | null } | null;
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
    location: null,
    reviewStatus: "unreviewed",
    correctedValue: null,
    valueOrigin: "extracted",
  };
}

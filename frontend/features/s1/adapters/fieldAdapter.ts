import type { ExtractedField, ValueProperty } from "../types";
import { resolveFieldKey } from "../utils/resolveFieldKey";

export interface BackendExtractionCandidateLike {
  candidate_id?: string;
  evidence_id?: string;
  document_id: string;
  field_name: string;
  /** Which record of the document the value belongs to (null for a single record). */
  record_index?: number | null;
  display_label: string;
  raw_value?: string | number | boolean | null;
  normalized_value: string | number | boolean | null;
  unit: string | null;
  confidence?: number | null;
  validation_flags?: string[] | null;
  /** With the flag ai_disagrees: what Claude read where the rules read another value (read-only). */
  ai_alternative?: {
    value: string | number | boolean | null;
    unit: string | null;
    source_reference?: { text_snippet?: string | null; page_number?: number | null } | null;
  } | null;
  source_reference?: {
    text_snippet?: string | null;
    page_number?: number | null;
    sheet_name?: string | null;
    cell_or_range?: string | null;
    parser_block_ids?: string[] | null;
    // Contract (source_reference.schema.json): normalized 0-1 {x, y, width, height}.
    // `w`/`h` are accepted for older payloads.
    bounding_box?: { x?: number; y?: number; width?: number; height?: number; w?: number; h?: number } | null;
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
    aiAlternative: mapAiAlternative(candidate),
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
                  w: Number(candidate.source_reference.bounding_box.width ?? candidate.source_reference.bounding_box.w ?? 0),
                  h: Number(candidate.source_reference.bounding_box.height ?? candidate.source_reference.bounding_box.h ?? 0),
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
    recordIndex: candidate.record_index ?? null,
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
  return utf8ToBase64(payload);
}

export function decodeReviewCandidateToken(token: string): BackendExtractionCandidateLike | null {
  try {
    return JSON.parse(base64ToUtf8(token)) as BackendExtractionCandidateLike;
  } catch {
    return null;
  }
}

/** Base64 of the text's UTF-8 bytes. `btoa` alone takes Latin-1 only and throws on a value
 *  such as "CO₂", "–" or "°F", which stopped the whole Evidence page from loading. */
function utf8ToBase64(text: string): string {
  if (typeof btoa === "function" && typeof TextEncoder === "function") {
    let binary = "";
    for (const byte of new TextEncoder().encode(text)) binary += String.fromCharCode(byte);
    return btoa(binary);
  }
  return Buffer.from(text, "utf8").toString("base64");
}

function base64ToUtf8(token: string): string {
  if (typeof atob === "function" && typeof TextDecoder === "function") {
    const binary = atob(token);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return new TextDecoder().decode(bytes);
  }
  return Buffer.from(token, "base64").toString("utf8");
}

function mapAiAlternative(candidate: BackendExtractionCandidateLike): ExtractedField["aiAlternative"] {
  const alt = candidate.ai_alternative;
  if (!alt || !(candidate.validation_flags ?? []).includes("ai_disagrees")) return undefined;
  return {
    value: alt.value === null || alt.value === undefined ? null : String(alt.value),
    unit: alt.unit ?? null,
    quote: alt.source_reference?.text_snippet ?? null,
    page: typeof alt.source_reference?.page_number === "number" ? alt.source_reference.page_number : null,
  };
}

function mapValidationFlags(flags?: string[] | null): ValueProperty[] {
  const allowed: ValueProperty[] = [
    "estimated_read",
    "unit_missing",
    "unit_ambiguous",
    "format_mismatch",
    "ai_suggested",
    "ai_disagrees",
    "ai_conflict",
  ];
  return (flags ?? []).filter((flag): flag is ValueProperty =>
    allowed.includes(flag as ValueProperty)
  );
}

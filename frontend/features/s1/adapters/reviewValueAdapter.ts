import type { EvidenceItem, ExtractedField } from "../types";
import type { ReviewValue, ScopePlacement, SourceKind } from "../types/review";
import { resolveCanonicalTypeDisplayName } from "./evidenceAdapter";
import { decodeReviewCandidateToken } from "./fieldAdapter";

/**
 * Extracted fields from the backend (one per candidate) as Extraction Review cards.
 * Only values the extractor found are cards: an empty field has nothing to accept
 * and stays visible as "n of m fields" in the Evidence Workspace.
 */
export function reviewValuesFromFields(fields: ExtractedField[], evidence: EvidenceItem[]): ReviewValue[] {
  const documents = new Map(evidence.map((item) => [item.documentId, item]));
  const periods = periodsByDocument(fields);
  const seen = new Map<string, number>();

  return fields
    .filter((field) => field.value !== null || field.correctedValue !== null)
    .map((field) => {
      const document = documents.get(field.documentId);
      const location = field.location;
      const page = location?.kind === "page" ? location.page : 1;
      const accepted = field.reviewStatus === "accepted";
      const corrected = field.reviewStatus === "corrected" || field.reviewStatus === "keyed_by_reviewer";
      // A card id must be unique even if an extraction repeats a candidate id.
      const repeat = seen.get(field.fieldKey) ?? 0;
      seen.set(field.fieldKey, repeat + 1);
      return {
        id: repeat ? `${field.fieldKey}#${repeat + 1}` : field.fieldKey,
        documentId: field.documentId,
        filename: document?.filename ?? field.documentId,
        documentType:
          document?.detectedType ??
          resolveCanonicalTypeDisplayName({ canonical_type_id: field.canonicalTypeId }) ??
          "Unclassified document",
        facilityId: null,
        notYetKnown: true,
        period: periods.get(field.documentId) ?? "Period not extracted",
        whatItIs: field.fieldLabel,
        scope: scopeOf(field.canonicalTypeId),
        value: (corrected ? field.correctedValue : field.value) ?? "",
        unit: field.unit ?? "",
        methodologyFieldId: fieldNameOf(field) ?? undefined,
        reviewState: accepted ? "accepted" : corrected ? "corrected" : "to_review",
        originalValue: corrected ? field.value : undefined,
        record: [
          {
            kind: "machine",
            actor: "Extraction",
            at: document?.uploadedAt ?? "",
            action: field.snippet ? `read "${field.snippet}"` : "extracted",
          },
          ...(accepted || corrected
            ? [{ kind: "human" as const, actor: "Reviewer", at: "", action: accepted ? "accepted as read" : "corrected" }]
            : []),
        ],
        sourceKind: sourceKindOf(document?.format),
        page,
        pageCount: page,
        span:
          location?.kind === "page" && location.region
            ? { page: location.page, ...location.region }
            : null,
        snippet: field.snippet,
        sheet: location?.kind === "cells" ? location.sheet : null,
        cell: location?.kind === "cells" ? location.range : null,
        reviewToken: field.reviewToken,
      } satisfies ReviewValue;
    });
}

function fieldNameOf(field: ExtractedField): string | null {
  const candidate = field.reviewToken ? decodeReviewCandidateToken(field.reviewToken) : null;
  return typeof candidate?.field_name === "string" ? candidate.field_name : null;
}

/** "2025-01-01 to 2025-06-30" from a document's own service period fields. */
function periodsByDocument(fields: ExtractedField[]): Map<string, string> {
  const ends = new Map<string, { start: Set<string>; end: Set<string> }>();
  for (const field of fields) {
    const name = fieldNameOf(field);
    const value = field.correctedValue ?? field.value;
    if (!value || (name !== "service_period_start" && name !== "service_period_end")) continue;
    const entry = ends.get(field.documentId) ?? { start: new Set(), end: new Set() };
    (name === "service_period_start" ? entry.start : entry.end).add(value);
    ends.set(field.documentId, entry);
  }
  const out = new Map<string, string>();
  ends.forEach(({ start, end }, documentId) => {
    if (start.size > 1 || end.size > 1) out.set(documentId, "Several service periods");
    else out.set(documentId, `${[...start][0] ?? "?"} to ${[...end][0] ?? "?"}`);
  });
  return out;
}

function scopeOf(canonicalTypeId: string | null): ScopePlacement {
  if (canonicalTypeId === "CT-S2-ELEC") return "scope2_location";
  if (canonicalTypeId?.startsWith("CT-S1-")) return "scope1";
  return "not_placed";
}

function sourceKindOf(format: EvidenceItem["format"] | undefined): SourceKind {
  if (format === "pdf") return "pdf";
  if (format === "image") return "image";
  if (format === "xlsx" || format === "csv") return "spreadsheet";
  return "text";
}

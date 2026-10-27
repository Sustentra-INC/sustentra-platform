import type { EvidenceItem, ExtractedField } from "../types";
import type { ReviewValue, ScopePlacement, SourceKind } from "../types/review";
import { resolveCanonicalTypeDisplayName } from "./evidenceAdapter";
import { anchorOf } from "../utils/sourceAnchor";
import { decodeReviewCandidateToken } from "./fieldAdapter";
import { formatDocumentPeriod, formatPrintedDate } from "../utils/formatPeriod";
import { asPrinted, printedUnitsByRecord } from "./printedValue";

/**
 * Extracted fields from the backend (one per candidate) as Extraction Review cards.
 * Only values the extractor found are cards: an empty field has nothing to accept
 * and stays visible as "n of m fields" in the Evidence Workspace.
 */
/** Fields the numbers depend on: when one is not found, the reviewer gets a card to enter it. */
const KEY_FIELDS = new Set([
  "fuel_type",
  "activity_quantity",
  "activity_unit",
  "service_period_start",
  "service_period_end",
  "transaction_date",
  "facility_name",
  "service_address",
  // refrigerant service records (simplified material balance)
  "refrigerant_type",
  "refrigerant_added",
  "refrigerant_recovered",
  "equipment_capacity",
  "service_date",
]);

export function reviewValuesFromFields(fields: ExtractedField[], evidence: EvidenceItem[]): ReviewValue[] {
  const documents = new Map(evidence.map((item) => [item.documentId, item]));
  const periods = periodsByDocument(fields);
  const printedUnits = printedUnitsByRecord(fields);
  const seen = new Map<string, number>();

  return fields
    .filter(
      (field) =>
        field.value !== null || field.correctedValue !== null || KEY_FIELDS.has(fieldNameOf(field) ?? "")
    )
    .map((field) => {
      const document = documents.get(field.documentId);
      const location = field.location;
      const candidate = field.reviewToken ? decodeReviewCandidateToken(field.reviewToken) : null;
      const rawValue = candidate?.raw_value ?? candidate?.normalized_value;
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
        unit: (corrected ? field.correctedUnit ?? field.unit : field.unit) ?? "",
        methodologyFieldId: fieldNameOf(field) ?? undefined,
        reviewState: accepted ? "accepted" : corrected ? "corrected" : "to_review",
        originalValue: corrected ? field.value : undefined,
        record: [
          {
            kind: "machine",
            actor: "Extraction",
            at: document?.uploadedAt ?? "",
            action: field.value === null ? "did not find this on the document" : field.snippet ? `read "${field.snippet}"` : "extracted",
          },
          ...(accepted || corrected
            ? [{
                kind: "human" as const,
                actor: field.reviewedBy ?? "Reviewer",
                at: field.reviewedAt ?? "",
                action: accepted
                  ? "accepted as read"
                  : field.value === null
                    ? "entered a value the extractor did not find"
                    : `corrected from ${field.value}${field.unit ? ` ${field.unit}` : ""}`,
              }]
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
        anchor: field.value === null ? null : anchorOf(document?.format, candidate?.source_reference),
        rawText: rawValue === null || rawValue === undefined ? null : String(rawValue),
        reviewToken: field.reviewToken,
        missing: field.value === null && field.correctedValue === null,
        asPrinted: corrected ? undefined : asPrinted(field, candidate, printedUnits),
      } satisfies ReviewValue;
    });
}

function fieldNameOf(field: ExtractedField): string | null {
  const candidate = field.reviewToken ? decodeReviewCandidateToken(field.reviewToken) : null;
  return typeof candidate?.field_name === "string" ? candidate.field_name : null;
}

/** The period a document covers, as a person reads it ("Feb 2025", "15 Jan – 14 Feb 2025"),
 *  from its service period, or the span of its transaction or service dates (fuel purchases
 *  and refrigerant service have a date, not a billing period). Never a raw ISO range. */
function periodsByDocument(fields: ExtractedField[]): Map<string, string> {
  const found = new Map<string, { start: Set<string>; end: Set<string>; dates: string[] }>();
  for (const field of fields) {
    const name = fieldNameOf(field);
    const value = field.correctedValue ?? field.value;
    if (!value || !name || !["service_period_start", "service_period_end", "transaction_date", "service_date"].includes(name)) continue;
    const entry = found.get(field.documentId) ?? { start: new Set(), end: new Set(), dates: [] };
    if (name === "service_period_start") entry.start.add(value);
    else if (name === "service_period_end") entry.end.add(value);
    else entry.dates.push(value);
    found.set(field.documentId, entry);
  }
  const out = new Map<string, string>();
  found.forEach(({ start, end, dates }, documentId) => {
    if (start.size || end.size) {
      if (start.size > 1 || end.size > 1) {
        const first = [...start].sort()[0];
        const last = [...end].sort().at(-1);
        out.set(documentId, first && last ? formatDocumentPeriod(first, last) : "Several service periods");
      } else {
        const [first, last] = [[...start][0], [...end][0]];
        out.set(
          documentId,
          first && last
            ? formatDocumentPeriod(first, last)
            : first
              ? `${formatPrintedDate(first)} – end not read`
              : `start not read – ${formatPrintedDate(last)}`
        );
      }
    } else if (dates.length) {
      const sorted = [...dates].sort();
      out.set(documentId, formatDocumentPeriod(sorted[0], sorted.at(-1) ?? sorted[0]));
    }
  });
  return out;
}

function scopeOf(canonicalTypeId: string | null): ScopePlacement {
  if (canonicalTypeId === "CT-S2-ELEC" || canonicalTypeId === "CT-S2-THERMAL") return "scope2_location";
  if (canonicalTypeId?.startsWith("CT-S1-")) return "scope1";
  return "not_placed";
}

function sourceKindOf(format: EvidenceItem["format"] | undefined): SourceKind {
  if (format === "pdf") return "pdf";
  if (format === "image") return "image";
  if (format === "xlsx" || format === "csv") return "spreadsheet";
  return "text";
}

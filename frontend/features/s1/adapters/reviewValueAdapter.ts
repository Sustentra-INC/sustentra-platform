import type { EvidenceItem, ExtractedField } from "../types";
import type { ReviewValue, ScopePlacement, SourceKind } from "../types/review";
import { resolveCanonicalTypeDisplayName } from "./evidenceAdapter";
import { anchorOf } from "../utils/sourceAnchor";
import { decodeReviewCandidateToken } from "./fieldAdapter";
import { formatDocumentPeriod, formatPrintedDate } from "../utils/formatPeriod";

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

/**
 * The value as the document prints it, for the card, when it reads differently from the value
 * recorded (`value`, which Accept and Correct send): dates as a bill prints them ("01 Feb
 * 2025"), quantities with their thousands separators ("1,250.5"), and a quantity converted for
 * the calculation (kWh read, MWh recorded) as read, "182,400" kWh, with `converted` set so the
 * card also shows what the calculation uses.
 */
function asPrinted(
  field: ExtractedField,
  candidate: ReturnType<typeof decodeReviewCandidateToken>,
  printedUnits: Map<string, string>
): ReviewValue["asPrinted"] {
  const value = field.value;
  if (value === null || !candidate) return undefined;
  const raw = candidate.raw_value;
  const converted = (candidate.validation_flags ?? []).includes("unit_converted");
  if (converted && typeof candidate.normalized_value === "number" && raw !== null && raw !== undefined && NUMBER.test(String(raw).trim())) {
    const unit = printedUnits.get(recordKeyOf(field.documentId, candidate.candidate_id));
    if (unit) return { value: grouped(String(raw).trim()), unit, converted: true };
  }
  if (converted && typeof candidate.normalized_value === "string" && typeof raw === "string" && raw.trim() && raw.trim() !== value) {
    return { value: raw.trim(), unit: "", converted: true }; // the unit itself: "kWh" read, MWh recorded
  }
  const date = formatPrintedDate(value);
  if (date !== value) return { value: date, unit: field.unit ?? "" };
  if (typeof candidate.normalized_value === "number" && NUMBER.test(value) && grouped(value) !== value) {
    return { value: grouped(value), unit: field.unit ?? "" };
  }
  return undefined;
}

/** A plain number, with or without thousands separators: "182400", "182,400", "-1250.5". */
const NUMBER = /^-?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$/;

/** "182400.5" -> "182,400.5"; "182,400" stays as it is. */
function grouped(text: string): string {
  const [whole, fraction] = text.replace(/,/g, "").split(".");
  const sign = whole.startsWith("-") ? "-" : "";
  const digits = whole.replace("-", "").replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${sign}${digits}${fraction !== undefined ? `.${fraction}` : ""}`;
}

/** The unit each record of a document printed, from its unit field's text as read ("kWh"). */
function printedUnitsByRecord(fields: ExtractedField[]): Map<string, string> {
  const units = new Map<string, string>();
  for (const field of fields) {
    if (fieldNameOf(field) !== "activity_unit") continue;
    const candidate = field.reviewToken ? decodeReviewCandidateToken(field.reviewToken) : null;
    const raw = candidate?.raw_value;
    if (typeof raw === "string" && raw.trim()) units.set(recordKeyOf(field.documentId, candidate?.candidate_id), raw.trim());
  }
  return units;
}

/** A document's record: the "::r2" a multi-record candidate id ends with, or the whole document. */
function recordKeyOf(documentId: string, candidateId: string | undefined): string {
  return `${documentId}|${/::r\d+$/.exec(candidateId ?? "")?.[0] ?? ""}`;
}

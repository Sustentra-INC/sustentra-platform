import type { ExtractedField } from "../types";
import type { ReviewValue } from "../types/review";
import { formatPrintedDate } from "../utils/formatPeriod";
import { decodeReviewCandidateToken } from "./fieldAdapter";

/*
 * A backend value as the document prints it (ReviewValue.asPrinted), for Extraction review's
 * cards. Display only: the value Accept and Correct record is the normalised one.
 */

/**
 * The value as the document prints it, for the card, when it reads differently from the value
 * recorded (`value`, which Accept and Correct send): dates as a bill prints them ("01 Feb
 * 2025"), quantities with their thousands separators ("1,250.5"), and a quantity converted for
 * the calculation (kWh read, MWh recorded) as read, "182,400" kWh, with `converted` set so the
 * card also shows what the calculation uses.
 */
export function asPrinted(
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
export function printedUnitsByRecord(fields: ExtractedField[]): Map<string, string> {
  const units = new Map<string, string>();
  for (const field of fields) {
    const candidate = field.reviewToken ? decodeReviewCandidateToken(field.reviewToken) : null;
    if (candidate?.field_name !== "activity_unit") continue;
    const raw = candidate?.raw_value;
    if (typeof raw === "string" && raw.trim()) units.set(recordKeyOf(field.documentId, candidate?.candidate_id), raw.trim());
  }
  return units;
}

/** A document's record: the "::r2" a multi-record candidate id ends with, or the whole document. */
function recordKeyOf(documentId: string, candidateId: string | undefined): string {
  return `${documentId}|${/::r\d+$/.exec(candidateId ?? "")?.[0] ?? ""}`;
}

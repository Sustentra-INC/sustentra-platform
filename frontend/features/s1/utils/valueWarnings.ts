/**
 * Which validation flags the backend puts on a value read from a document make "Accept all" leave
 * the value for the reviewer. The flags come from the readers (backend/app/services: the
 * extraction_candidate_service, the stationary, mobile and refrigerant extractors, bill_notes and
 * ai_extraction).
 *
 * A flag is a warning unless it is listed here as only informing: a flag the app does not know
 * (a reader added one later) holds the value back, the safe side for an audit.
 */
export const INFORMATIONAL_FLAGS: ReadonlySet<string> = new Set([
  "field_not_found", // nothing was read: the card is a missing value, which is never accepted in bulk anyway
  "unit_converted", // converted by a fixed factor; the card shows the value as printed and the one the calculation uses
  "biofuel_blend", // the fuel is a blend; its share is read as its own value
]);

/** Sustentra's AI flags have their own note and their own rule (needsOwnAccept). */
const AI_FLAGS: ReadonlySet<string> = new Set(["ai_suggested", "ai_conflict"]);

/** Plain words for the flags that hold a value back. A flag not named here reads "flagged by the reading". */
const WORDS: Record<string, string> = {
  unit_ambiguous: "unit unclear",
  unit_missing: "unit missing",
  unit_conversion_not_implemented: "unit not converted",
  estimated_read: "estimated reading",
  format_mismatch: "unexpected format",
  value_not_in_allowed_values: "unexpected value",
  negative_quantity: "negative quantity",
  period_start_after_end: "period dates out of order",
  amount_not_a_number: "amount not a number",
  card_number_masked: "card number, not an account",
  montreal_protocol_gas: "ozone-depleting gas",
  quantity_times_package_size: "worked out from package size",
  approximate: "approximate amount",
  filled_from_document: "filled in from elsewhere on the document",
  purchase_not_equipment_charge: "a purchase, not a charge",
  possible_summary_or_continuation: "possible summary line",
  extracted_value_changed_since_review: "changed since it was reviewed",
  ai_disagrees: "Sustentra's AI read another value",
  unsupported_extraction_method: "could not be read",
};
const UNKNOWN_WORDS = "flagged by the reading";

/** The flags of a value that are warnings (kept in the order the backend sent them, without repeats). */
export function warningFlags(flags: readonly string[] | undefined | null): string[] {
  return [...new Set((flags ?? []).filter((f) => !INFORMATIONAL_FLAGS.has(f) && !AI_FLAGS.has(f)))];
}

/** The reasons, in plain words, without repeats. */
export function warningWords(flags: readonly string[]): string[] {
  return [...new Set(flags.map((f) => WORDS[f] ?? UNKNOWN_WORDS))];
}

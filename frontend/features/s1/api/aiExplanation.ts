/**
 * Why Sustentra's AI suggested something: the explanation the server builds from what is stored with the
 * suggestion (backend services/methodology_explanation.py and ai_facility.explanation). Every Methodology
 * suggestion, the facility suggestion and the other "suggested by Sustentra's AI" items show it in the same popover.
 */

export const NO_REASON = "Reason not recorded for this suggestion. Re-read the reports to get one.";

export interface AiExplanationItem {
  /** Which entry or option this is, when a suggestion has several ("PPA or VPPA"); null for a single quote. */
  label: string | null;
  /** The AI's own reason (at most 240 characters); null when none was recorded. */
  reason: string | null;
  quote: string;
  document_id: string;
  file_name: string;
  page: number | null;
  /** "page 4", "Sheet1, B12" or "". */
  location: string;
  /** What the suggestion passed, worked out from the stored value and quote. */
  checks: string[];
  /** What was worked out rather than printed, and how ("Start date implied: ..."). */
  implied: string[];
}

export interface AiExplanation {
  reason: string | null;
  reason_note: string | null;
  read_at?: string | null;
  model?: string | null;
  items: AiExplanationItem[];
  /** A facility read that stopped before the end of the document: what it did not reach ("pages 12–40"). */
  read_in_part?: string | null;
  /** A facility read whose parts point at more than one facility: each, with its quote and page. */
  candidates?: { facility_id: string; quote: string; page: number | null }[];
}

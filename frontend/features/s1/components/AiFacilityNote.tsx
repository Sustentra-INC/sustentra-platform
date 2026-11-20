import { NO_REASON, type AiExplanation } from "../api/aiExplanation";
import { AI_FACILITY } from "../constants/copy";
import { AiExplainPopover } from "./AiExplainPopover";

/**
 * What Sustentra's AI suggested for a bill that names no facility: "Facility suggested by Sustentra's AI" (a button
 * that opens why: its reason, the quote and the checks) with the words it cited, and a one-click "Place on
 * <facility>" for the reviewer. The bill stays unplaced until the reviewer clicks: the click is the reviewer's own
 * facility decision (audited on the server). Used on the Evidence tree row and the review screen, in the same words.
 * With no server explanation (an older server) the popover shows the quote and place only, and says no reason was
 * recorded.
 */
export function AiFacilityNote({
  facilityName,
  quote,
  where,
  onPlace,
  disabled,
  explanation,
  onOpenDocument,
}: {
  facilityName: string;
  quote: string;
  where: string;
  onPlace: () => void;
  disabled?: boolean;
  explanation?: AiExplanation | null;
  /** Opens the document the quote is on (the popover's link). */
  onOpenDocument?: (documentId: string, page?: number | null) => void;
}) {
  const shown: AiExplanation = explanation ?? {
    reason: null,
    reason_note: NO_REASON,
    items: [{ label: null, reason: null, quote, document_id: "", file_name: "", page: null, location: where, checks: [], implied: [] }],
  };
  return (
    <div className="s1-muted s1-ai-facility" data-testid="ai-facility-note">
      <div>
        <AiExplainPopover label={AI_FACILITY.suggested} explanation={shown} onOpenDocument={onOpenDocument} testId="ai-facility-explain" />
      </div>
      <div>
        “{quote}” · {where}
      </div>
      <button className="s1-button s1-button--compact" type="button" disabled={disabled} onClick={onPlace}>
        {AI_FACILITY.place(facilityName)}
      </button>
    </div>
  );
}

import { AI_FACILITY } from "../constants/copy";

/**
 * What Claude suggested for a bill that names no facility: "Facility suggested by Claude" with the words it
 * cited, and a one-click "Place on <facility>" for the reviewer. The bill stays unplaced until the reviewer clicks:
 * the click is the reviewer's own facility decision (audited on the server). Used on the Evidence tree row and the
 * review screen, in the same words.
 */
export function AiFacilityNote({
  facilityName,
  quote,
  where,
  onPlace,
  disabled,
}: {
  facilityName: string;
  quote: string;
  where: string;
  onPlace: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="s1-muted s1-ai-facility" data-testid="ai-facility-note">
      <div>{AI_FACILITY.suggested}</div>
      <div>
        “{quote}” · {where}
      </div>
      <button className="s1-button s1-button--compact" type="button" disabled={disabled} onClick={onPlace}>
        {AI_FACILITY.place(facilityName)}
      </button>
    </div>
  );
}

import { NO_REASON, type AiExplanation } from "../api/aiExplanation";
import { AI_TYPE } from "../constants/copy";
import type { EvidenceItem } from "../types";
import { AiExplainPopover } from "./AiExplainPopover";

/**
 * What Claude said about a document's type: "Type suggested by Claude, please confirm" with the
 * words it cited, when it set the type; or, in words, that it disagreed with the rules (the type
 * was not changed). The existing type control changes the type.
 */
/** The quote and page the type was read from; the AI's reason is not kept for a type yet, and the popover says so. */
function explanationOfType(ai: { quote: string; page?: number | null }): AiExplanation {
  const location = ai.page != null ? `page ${ai.page}` : "";
  return {
    reason: null,
    reason_note: NO_REASON,
    items: [
      {
        label: null,
        reason: null,
        quote: ai.quote,
        document_id: "",
        file_name: "",
        page: ai.page ?? null,
        location,
        checks: ai.quote ? [`The quote was found on the document${location ? ` (${location})` : ""} when it was read.`] : [],
        implied: [],
      },
    ],
  };
}

export function AiTypeNote({ item }: { item: Pick<EvidenceItem, "aiType" | "detectedType" | "typeConfirmed"> }) {
  const ai = item.aiType;
  if (!ai) return null;
  if (ai.used) {
    if (item.typeConfirmed) return null;
    return (
      <div className="s1-muted" data-testid="ai-type-note">
        <div>
          <AiExplainPopover label={AI_TYPE.suggested} explanation={explanationOfType(ai)} testId="ai-type-explain" />
        </div>
        <div>
          “{ai.quote}”{ai.page != null ? ` · page ${ai.page}` : ""}
        </div>
      </div>
    );
  }
  if (!ai.disagrees) return null;
  return (
    <div className="s1-muted" data-testid="ai-type-note">
      {AI_TYPE.disagreesOn(item.detectedType ?? "an unknown type", ai.typeName)}
      <div>
        “{ai.quote}”{ai.page != null ? ` · page ${ai.page}` : ""}
      </div>
    </div>
  );
}

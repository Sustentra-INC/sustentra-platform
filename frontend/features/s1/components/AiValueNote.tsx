import { NO_REASON, type AiExplanation } from "../api/aiExplanation";
import { AI_VALUE } from "../constants/copy";
import { STATE_ROLE_BY_PAIR } from "../constants/stateIndicators";
import type { ReviewValue } from "../types/review";
import { AiExplainPopover } from "./AiExplainPopover";
import { StateIndicator } from "./StateIndicator";

/** The bill says the utility estimated this reading (backend flag `estimated_read`): the value is as printed. */
export function EstimatedReadNote({ value }: { value: Pick<ReviewValue, "estimatedRead"> }) {
  if (!value.estimatedRead) return null;
  return (
    <div className="s1-muted" data-testid="estimated-read-note">
      <StateIndicator
        dimension="valueProperty"
        value="estimated_read"
        label="Estimated read"
        explain="The utility estimated this reading instead of reading the meter. The value is as printed on the bill."
      />
    </div>
  );
}

/**
 * What Claude read for a value (backend services/ai_extraction.py), on the value's card.
 * A value Claude read where the rules found nothing carries "Suggested by Claude" with the
 * verified snippet and its page, until a reviewer accepts or corrects it; it is never
 * pre-accepted. Where the rules read a value and Claude read another, the card says so with
 * Claude's value and quote. The chips are the existing state chips.
 */
/**
 * What is known of a read value from its card: the verified snippet and its page. The AI's reason is not kept for
 * a read value yet, so the popover says so; the one check it states is the one the reading is kept under.
 */
function explanationOfValue(value: Pick<ReviewValue, "snippet" | "page" | "sourceKind">): AiExplanation {
  const paged = value.sourceKind === "pdf" || value.sourceKind === "image";
  const location = paged && value.page ? `page ${value.page}` : "";
  return {
    reason: null,
    reason_note: NO_REASON,
    items: [
      {
        label: null,
        reason: null,
        quote: value.snippet ?? "",
        document_id: "",
        file_name: "",
        page: paged && value.page ? value.page : null,
        location,
        checks: value.snippet ? [`The quote was found on the document${location ? ` (${location})` : ""} when it was read.`] : [],
        implied: [],
      },
    ],
  };
}

export function AiValueNote({ value }: { value: Pick<ReviewValue, "ai" | "snippet" | "page" | "reviewState" | "sourceKind"> }) {
  const ai = value.ai;
  if (!ai) return null;
  const suggested = ai.suggested && value.reviewState === "to_review";
  if (!suggested && !ai.disagrees && !(ai.conflict && value.reviewState === "to_review")) return null;
  return (
    <div className="s1-muted" data-testid="ai-value-note">
      {suggested ? (
        <>
          <AiExplainPopover
            label={AI_VALUE.suggested}
            className={`s1-state s1-state--${STATE_ROLE_BY_PAIR.valueProperty?.ai_suggested ?? "unmapped"}`}
            explanation={explanationOfValue(value)}
            testId="ai-value-explain"
          />
          {value.snippet ? (
            <div>
              “{value.snippet}”{value.sourceKind === "pdf" || value.sourceKind === "image" ? ` · page ${value.page}` : ""}
            </div>
          ) : null}
        </>
      ) : null}
      {ai.conflict && value.reviewState === "to_review" ? (
        <div>
          <StateIndicator
            dimension="valueProperty"
            value="ai_conflict"
            label={AI_VALUE.conflict}
            explain={AI_VALUE.conflictHelp}
          />
        </div>
      ) : null}
      {ai.disagrees ? (
        <>
          <StateIndicator
            dimension="valueProperty"
            value="ai_disagrees"
            label={AI_VALUE.disagrees}
            explain={AI_VALUE.disagreesHelp}
          />
          <div>
            {ai.disagrees.value}
            {ai.disagrees.unit ? ` ${ai.disagrees.unit}` : ""}
            {ai.disagrees.quote ? ` · “${ai.disagrees.quote}”` : ""}
            {ai.disagrees.page != null ? ` · page ${ai.disagrees.page}` : ""}
          </div>
        </>
      ) : null}
    </div>
  );
}

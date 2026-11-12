import { AI_VALUE } from "../constants/copy";
import type { ReviewValue } from "../types/review";
import { StateIndicator } from "./StateIndicator";

/**
 * What Claude read for a value (backend services/ai_extraction.py), on the value's card.
 * A value Claude read where the rules found nothing carries "Suggested by Claude" with the
 * verified snippet and its page, until a reviewer accepts or corrects it; it is never
 * pre-accepted. Where the rules read a value and Claude read another, the card says so with
 * Claude's value and quote. The chips are the existing state chips.
 */
export function AiValueNote({ value }: { value: Pick<ReviewValue, "ai" | "snippet" | "page" | "reviewState" | "sourceKind"> }) {
  const ai = value.ai;
  if (!ai) return null;
  const suggested = ai.suggested && value.reviewState === "to_review";
  if (!suggested && !ai.disagrees && !(ai.conflict && value.reviewState === "to_review")) return null;
  return (
    <div className="s1-muted" data-testid="ai-value-note">
      {suggested ? (
        <>
          <StateIndicator
            dimension="valueProperty"
            value="ai_suggested"
            label={AI_VALUE.suggested}
            explain={AI_VALUE.suggestedHelp}
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

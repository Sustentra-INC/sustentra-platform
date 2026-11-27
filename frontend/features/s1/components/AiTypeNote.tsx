import { NO_REASON, type AiExplanation } from "../api/aiExplanation";
import { AI_TYPE, READ_IN_PART } from "../constants/copy";
import type { EvidenceItem } from "../types";
import { AiExplainPopover } from "./AiExplainPopover";

/**
 * What Sustentra's AI said about a document's type: "Type suggested by Sustentra's AI, please confirm" with the
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

const MAX_QUOTE = 160;

/** The quote as it is shown: a very long line is cut, so one row never grows without limit. */
function shortQuote(quote: string): string {
  const text = quote.trim();
  return text.length > MAX_QUOTE ? `${text.slice(0, MAX_QUOTE).trimEnd()}…` : text;
}

/** The lines under the quote: other types parts of the document were read as, and what the read did not reach. */
function TypeReadNotes({ ai }: { ai: NonNullable<EvidenceItem["aiType"]> }) {
  return (
    <>
      {ai.otherTypes?.length ? <div data-testid="ai-type-others">{AI_TYPE.otherTypes(ai.otherTypes)}</div> : null}
      {ai.readInPart ? <div data-testid="ai-type-read-in-part">{READ_IN_PART.pages(ai.readInPart)}</div> : null}
    </>
  );
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
        <TypeReadNotes ai={ai} />
      </div>
    );
  }
  if (!ai.disagrees || item.typeConfirmed) return null;
  const quote = shortQuote(ai.quote);
  return (
    <div className="s1-muted" data-testid="ai-type-note" style={{ overflowWrap: "anywhere" }}>
      <div>
        <span className="s1-chip" data-testid="ai-type-check">
          {AI_TYPE.toCheck}
        </span>
      </div>
      <div>{AI_TYPE.disagreesOn(item.detectedType ?? "an unknown type", ai.typeName)}</div>
      {quote ? (
        <div>
          “{quote}”{ai.page != null ? ` · page ${ai.page}` : ""}
        </div>
      ) : null}
      <TypeReadNotes ai={ai} />
    </div>
  );
}

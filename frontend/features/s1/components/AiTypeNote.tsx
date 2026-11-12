import { AI_TYPE } from "../constants/copy";
import type { EvidenceItem } from "../types";

/**
 * What Claude said about a document's type: "Type suggested by Claude, please confirm" with the
 * words it cited, when it set the type; or, in words, that it disagreed with the rules (the type
 * was not changed). The existing type control changes the type.
 */
export function AiTypeNote({ item }: { item: Pick<EvidenceItem, "aiType" | "detectedType" | "typeConfirmed"> }) {
  const ai = item.aiType;
  if (!ai) return null;
  if (ai.used) {
    if (item.typeConfirmed) return null;
    return (
      <div className="s1-muted" data-testid="ai-type-note">
        <div>{AI_TYPE.suggested}</div>
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

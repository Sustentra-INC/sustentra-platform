import type { MethodologyReviewData } from "../api/methodologyReview";

/**
 * How many facts Methodology review has read from each document: the fields whose suggestion cites it, as its
 * source or as the source of one entry of a list suggestion. A field counts once per document, however many
 * of its entries quote that document.
 */
export function factsReadByDocument(data: Pick<MethodologyReviewData, "fields">): Map<string, number> {
  const counts = new Map<string, number>();
  for (const record of data.fields) {
    const suggestion = record.suggestion;
    if (!suggestion) continue;
    const cited = new Set<string>();
    if (suggestion.document_id) cited.add(suggestion.document_id);
    for (const entry of suggestion.evidence ?? []) if (entry.document_id) cited.add(entry.document_id);
    for (const id of cited) counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  return counts;
}

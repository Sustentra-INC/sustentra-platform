import type { PageMark, ValueReviewState } from "../types/review";

/**
 * A highlight on an uploaded page or file can hold several values (an amount and its unit read
 * from one line). It takes the most urgent of their states, the order the demo's documents use
 * (DemoDocument, after "missing", which is never drawn here): one value still to review keeps
 * the highlight "to review", so a done-looking mark never hides work left.
 */
const MOST_URGENT_FIRST: readonly ValueReviewState[] = ["to_review", "requested", "corrected", "accepted"];

export function markState(marks: Pick<PageMark, "reviewState">[]): ValueReviewState {
  return MOST_URGENT_FIRST.find((state) => marks.some((m) => m.reviewState === state)) ?? "to_review";
}

/** A state in words, as the value cards say it, so a highlight is never colour alone. */
const STATE_WORD: Record<ValueReviewState, string> = {
  to_review: "to review",
  accepted: "accepted",
  corrected: "corrected",
  requested: "requested",
};

/** A highlight's name, for its tooltip and screen readers: each value it holds with its state,
 *  "Utility: Puget Sound Energy, accepted". */
export function markName(marks: Pick<PageMark, "label" | "reviewState">[]): string {
  return marks.map((m) => `${m.label}, ${STATE_WORD[m.reviewState]}`).join(" · ");
}

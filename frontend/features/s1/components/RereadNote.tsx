import { REREAD } from "../constants/copy";
import type { ReviewValue } from "../types/review";

/**
 * After a document is read again, the backend says which earlier decisions no longer apply
 * (backend S1-BE-014): the value is back to review, and the card says why in the plain words the
 * API's flag stands for. A correction that carried over a changed value says so too. Existing
 * muted text style; the state itself is the card's own "to review" state.
 */
export function RereadNote({
  value,
}: {
  value: Pick<ReviewValue, "rereadChanged" | "valueChangedSinceReview" | "reviewState">;
}) {
  if (value.rereadChanged && value.reviewState === "to_review") {
    return (
      <div className="s1-muted s1-xr-reread" data-testid="reread-note">
        {REREAD.reviewAgain}
      </div>
    );
  }
  if (value.valueChangedSinceReview) {
    return (
      <div className="s1-muted s1-xr-reread" data-testid="reread-note">
        {REREAD.valueChanged}
      </div>
    );
  }
  return null;
}

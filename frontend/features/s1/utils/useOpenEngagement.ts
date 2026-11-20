import { useLayoutEffect, useState } from "react";

/** The check a page keeps, plus ``markOpen`` for the moment it switches engagement. */
export type OpenEngagement = ((engagementId: string) => boolean) & { markOpen: (engagementId: string) => void };

/**
 * Whether an engagement is still the open one, for an answer that arrives after a request was started.
 *
 * A request that takes a while (deleting a line with hundreds of documents) can finish after the user has
 * switched to another engagement. The answer belongs to the engagement it was asked for: if that is no longer
 * the open one, the page drops it instead of writing it into the new engagement's state. The returned function
 * is stable and always reads the engagement open at the time of the call.
 *
 * The engagement is recorded the moment the page switches, not when React next runs effects: call
 * ``markOpen(id)`` in the handler that switches, before the state is set, so an answer that lands between
 * the switch and the next commit is already for the wrong engagement. The ref also follows the prop in a
 * layout effect (before the browser paints), as a backstop for any switch that does not call ``markOpen``.
 */
export function useOpenEngagement(openEngagementId: string): OpenEngagement {
  const [api] = useState<OpenEngagement>(() => {
    let current = openEngagementId;
    const check = (engagementId: string) => current === engagementId;
    const markOpen = (engagementId: string) => {
      current = engagementId;
    };
    return Object.assign(check, { markOpen });
  });
  useLayoutEffect(() => {
    api.markOpen(openEngagementId);
  }, [api, openEngagementId]);
  return api;
}

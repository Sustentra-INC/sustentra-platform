import { useCallback, useEffect, useRef } from "react";

/**
 * Whether an engagement is still the open one, for an answer that arrives after a request was started.
 *
 * A request that takes a while (deleting a line with hundreds of documents) can finish after the user has
 * switched to another engagement. The answer belongs to the engagement it was asked for: if that is no longer
 * the open one, the page drops it instead of writing it into the new engagement's state. The returned function
 * is stable and always reads the engagement open at the time of the call.
 */
export function useOpenEngagement(openEngagementId: string): (engagementId: string) => boolean {
  const open = useRef(openEngagementId);
  useEffect(() => {
    open.current = openEngagementId;
  }, [openEngagementId]);
  return useCallback((engagementId: string) => open.current === engagementId, []);
}

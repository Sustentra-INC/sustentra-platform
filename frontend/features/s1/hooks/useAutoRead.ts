import { useEffect, useRef, useState } from "react";

import { autoReadActive, getAutoRead, type AutoRead } from "../api/methodologyReview";

export const AUTO_READ_POLL_MS = 3000;
/** After something changed (an upload, a finished read) the status is looked at a few times in this rhythm even when
 *  nothing is waiting yet: the wait for the rest of a batch starts a moment after the read completes. */
export const AUTO_READ_SETTLE_MS = 1500;
const SETTLE_LOOKS = 3;

/**
 * Whether Sustentra's AI is reading the engagement's summary documents by itself. Fetches when enabled and
 * whenever `nudge` changes, then polls every 3 s while a read is waiting or running (a few times in the settle
 * rhythm after a nudge, in case one is about to start). A failed poll ends the polling quietly: the Evidence page
 * does not depend on it.
 */
export function useAutoRead({ enabled, engagementId, nudge }: { enabled: boolean; engagementId: string; nudge: number }): AutoRead | null {
  const [state, setState] = useState<{ scope: string; value: AutoRead | null }>({ scope: "", value: null });
  const alive = useRef(0);

  useEffect(() => {
    if (!enabled || !engagementId) return;
    const mine = ++alive.current;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let looks = 0;

    const look = async () => {
      let found: AutoRead | null;
      try {
        found = await getAutoRead(engagementId);
      } catch {
        return;
      }
      if (alive.current !== mine) return;
      setState((cur) => (cur.scope === engagementId && JSON.stringify(cur.value) === JSON.stringify(found) ? cur : { scope: engagementId, value: found }));
      looks += 1;
      if (autoReadActive(found)) timer = setTimeout(() => void look(), AUTO_READ_POLL_MS);
      else if (looks < SETTLE_LOOKS) timer = setTimeout(() => void look(), AUTO_READ_SETTLE_MS);
    };
    void look();
    return () => {
      alive.current += 1;
      if (timer !== null) clearTimeout(timer);
    };
  }, [enabled, engagementId, nudge]);

  return state.scope === engagementId ? state.value : null;
}

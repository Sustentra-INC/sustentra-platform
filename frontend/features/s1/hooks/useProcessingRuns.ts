import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { isActiveRun, listProcessingRuns, type ProcessingRunView } from "../api/processingRuns";

export const POLL_FAST_MS = 2000;
export const POLL_SLOW_MS = 5000;
/** Runs that have stayed active this long are polled at the slow rate. */
export const SLOW_AFTER_MS = 60_000;
/** The shortest gap between polls while the tab is hidden. */
export const HIDDEN_MS = 15_000;
export const ERROR_MAX_MS = 30_000;

type Runs = Record<string, ProcessingRunView>;

const NO_RUNS: Runs = {};
const NO_IDS: string[] = [];

interface Follower {
  track: (run: ProcessingRunView) => void;
}

export interface UseProcessingRunsOptions {
  /** Backend mode only. Disabled, nothing is fetched and nothing is scheduled. */
  enabled: boolean;
  engagementId: string;
  /** Runs seen going from queued/in_progress to completed/failed, once each, batched per poll. */
  onFinished: (runs: ProcessingRunView[]) => void;
  /** A failed poll. Return true when it was handled (the session ended): polling stops. */
  onError?: (error: unknown) => boolean;
}

function sameRun(a: ProcessingRunView, b: ProcessingRunView): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Follows the engagement's processing runs. It fetches once when it is enabled (which picks
 * up reads still going after a reload) and then polls only while a run is queued or in
 * progress: every 2 s, every 5 s once runs have been active for a minute, and no more often
 * than every 15 s while the tab is hidden. A failed poll is retried with a growing delay.
 */
export function useProcessingRuns({ enabled, engagementId, onFinished, onError }: UseProcessingRunsOptions): {
  /** The latest known run for each document. */
  runs: Record<string, ProcessingRunView>;
  /** Documents whose run is queued or in progress. */
  readingIds: string[];
  /** Follow a run from an upload or a read request. */
  track: (run: ProcessingRunView) => void;
} {
  const [stored, setStored] = useState<{ scope: string; runs: Runs }>({ scope: "", runs: NO_RUNS });
  const callbacks = useRef({ onFinished, onError });
  const generation = useRef(0);
  const follower = useRef<Follower | null>(null);

  useEffect(() => {
    callbacks.current = { onFinished, onError };
  });

  useEffect(() => {
    if (!enabled || !engagementId) return;

    const mine = ++generation.current;
    const alive = () => generation.current === mine;

    let current: Runs = {};
    /** `${run_id}:${status}` of the finished runs already handed to onFinished. */
    const reported = new Set<string>();
    /** Documents tracked while a fetch was in flight: that fetch may predate the run. */
    const touched = new Set<string>();
    let timer: ReturnType<typeof setTimeout> | null = null;
    let inFlight = false;
    let halted = false;
    let activeSince: number | null = null;
    let errorDelay = POLL_FAST_MS;

    const publish = () => setStored({ scope: engagementId, runs: current });

    const schedule = (delay: number) => {
      if (!alive() || halted) return;
      if (timer !== null) clearTimeout(timer);
      const wait = document.visibilityState === "hidden" ? Math.max(delay, HIDDEN_MS) : delay;
      timer = setTimeout(() => {
        timer = null;
        void poll();
      }, wait);
    };

    const pollDelay = () =>
      activeSince !== null && Date.now() - activeSince >= SLOW_AFTER_MS ? POLL_SLOW_MS : POLL_FAST_MS;

    async function poll() {
      if (!alive() || inFlight) return;
      inFlight = true;
      touched.clear();
      let items: ProcessingRunView[];
      try {
        items = await listProcessingRuns(engagementId);
      } catch (error) {
        inFlight = false;
        if (!alive()) return;
        if (callbacks.current.onError?.(error)) {
          halted = true;
          return;
        }
        errorDelay = Math.min(errorDelay * 2, ERROR_MAX_MS);
        schedule(errorDelay);
        return;
      }
      inFlight = false;
      if (!alive()) return;
      errorDelay = POLL_FAST_MS;

      const next = { ...current };
      const finished: ProcessingRunView[] = [];
      let changed = false;
      for (const item of items) {
        if (item.engagement_id !== engagementId || touched.has(item.document_id)) continue;
        const before = next[item.document_id];
        if (before && sameRun(before, item)) continue;
        next[item.document_id] = item;
        changed = true;
        if (before && isActiveRun(before) && !isActiveRun(item)) {
          const key = `${item.run_id}:${item.status}`;
          if (!reported.has(key)) {
            reported.add(key);
            finished.push(item);
          }
        }
      }
      if (changed) {
        current = next;
        publish();
      }

      if (Object.values(current).some(isActiveRun)) {
        if (activeSince === null) activeSince = Date.now();
        schedule(pollDelay());
      } else {
        activeSince = null;
      }
      if (finished.length > 0) callbacks.current.onFinished(finished);
    }

    follower.current = {
      track(run) {
        if (!alive() || run.engagement_id !== engagementId) return;
        current = { ...current, [run.document_id]: run };
        if (inFlight) touched.add(run.document_id);
        publish();
        if (isActiveRun(run)) {
          activeSince = Date.now();
          if (!inFlight) schedule(POLL_FAST_MS);
        }
      },
    };

    const onVisibilityChange = () => {
      if (document.visibilityState !== "visible" || timer === null) return;
      clearTimeout(timer);
      timer = null;
      void poll();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);

    void poll();

    return () => {
      generation.current += 1;
      if (timer !== null) clearTimeout(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      follower.current = null;
      setStored({ scope: "", runs: NO_RUNS });
    };
  }, [enabled, engagementId]);

  const track = useCallback((run: ProcessingRunView) => {
    follower.current?.track(run);
  }, []);

  const runs = enabled && stored.scope === engagementId ? stored.runs : NO_RUNS;
  const readingIds = useMemo(() => {
    const ids = Object.values(runs)
      .filter(isActiveRun)
      .map((run) => run.document_id);
    return ids.length > 0 ? ids : NO_IDS;
  }, [runs]);

  return { runs, readingIds, track };
}

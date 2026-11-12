import { useEffect, useRef, useState } from "react";

import { ApiError } from "../../../lib/api";
import { BATCH_POLL_MS, getDocumentBatch, type BatchView } from "../api/documentBatches";

export const BATCH_LOAD_FAILED = "Progress couldn't be loaded. Refresh to try again.";
/** Consecutive failed polls (server errors, network) after which polling stops. */
export const BATCH_MAX_FAILURES = 3;
/** Shown when the batch for several dropped files could not be made: they went up without one. */
export const BATCH_NOT_CREATED = "These files were uploaded without a batch.";

export interface UseBatchProgressOptions {
  /** Backend mode only. Disabled, or with no batch, nothing is fetched and nothing is scheduled. */
  enabled: boolean;
  engagementId: string;
  batchId: string | null;
  /** Files are still being sent: the batch is not over even if what has arrived is all read. */
  uploading: boolean;
  /** A failed poll. Return true when it was handled (the session ended): polling stops. */
  onError?: (error: unknown) => boolean;
}

/**
 * Follows one batch: fetches it, then again every 3 s while anything in it is still waiting or
 * being read (or files are still going up), and stops once the API says it is complete.
 * Any 4xx stops polling at once (the batch is gone or not ours). A 5xx or a network error is
 * tried again after 3 s, then 6 s, and polling stops at the third failure in a row; `error`
 * then says so, and the last table that loaded stays.
 */
export function useBatchProgress({
  enabled,
  engagementId,
  batchId,
  uploading,
  onError,
}: UseBatchProgressOptions): { view: BatchView | null; error: string | null } {
  const [stored, setStored] = useState<{ batchId: string; view: BatchView | null; error: string | null } | null>(null);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  });

  useEffect(() => {
    if (!enabled || !batchId) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let failures = 0;

    const poll = async () => {
      let wait: number | null = BATCH_POLL_MS;
      try {
        const view = await getDocumentBatch(engagementId, batchId);
        if (!alive) return;
        failures = 0;
        setStored({ batchId, view, error: null });
        wait = uploading || !view.complete ? BATCH_POLL_MS : null;
      } catch (error) {
        if (!alive) return;
        if (onErrorRef.current?.(error)) return;
        failures += 1;
        const clientError = error instanceof ApiError && error.status >= 400 && error.status < 500;
        if (clientError || failures >= BATCH_MAX_FAILURES) {
          setStored((current) => ({
            batchId,
            view: current && current.batchId === batchId ? current.view : null,
            error: BATCH_LOAD_FAILED,
          }));
          return;
        }
        wait = BATCH_POLL_MS * 2 ** (failures - 1);
      }
      if (wait !== null) timer = setTimeout(() => void poll(), wait);
    };

    void poll();
    return () => {
      alive = false;
      if (timer !== null) clearTimeout(timer);
    };
  }, [enabled, engagementId, batchId, uploading]);

  return stored && stored.batchId === batchId
    ? { view: stored.view, error: stored.error }
    : { view: null, error: null };
}

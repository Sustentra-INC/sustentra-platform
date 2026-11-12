import { useEffect, useRef, useState } from "react";

import { BATCH_POLL_MS, getDocumentBatch, type BatchView } from "../api/documentBatches";

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
 * A failed poll is tried again on the next beat.
 */
export function useBatchProgress({
  enabled,
  engagementId,
  batchId,
  uploading,
  onError,
}: UseBatchProgressOptions): BatchView | null {
  const [stored, setStored] = useState<{ batchId: string; view: BatchView } | null>(null);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  });

  useEffect(() => {
    if (!enabled || !batchId) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const poll = async () => {
      let again = true;
      try {
        const view = await getDocumentBatch(engagementId, batchId);
        if (!alive) return;
        setStored({ batchId, view });
        again = uploading || !view.complete;
      } catch (error) {
        if (!alive) return;
        if (onErrorRef.current?.(error)) return;
      }
      if (again) timer = setTimeout(() => void poll(), BATCH_POLL_MS);
    };

    void poll();
    return () => {
      alive = false;
      if (timer !== null) clearTimeout(timer);
    };
  }, [enabled, engagementId, batchId, uploading]);

  return stored && stored.batchId === batchId ? stored.view : null;
}

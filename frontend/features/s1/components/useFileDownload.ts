"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { downloadErrorMessage, downloadExcel } from "../api/downloadFile";
import { isSessionEnded, userFacingApiError } from "../api/s1Backend";

/**
 * One download at a time: ``start`` fetches and saves the file; ``busyId`` names the one in progress (so a second
 * click does nothing), ``message`` is the plain-words reason when one failed. ``onError`` is the screen's own
 * handler for an ended session (returns true when it dealt with it); ``onDone`` runs after a file is saved.
 */
export function useFileDownload(onError?: (error: unknown) => boolean, onDone?: () => void) {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const inFlight = useRef(false);
  const alive = useRef(true);
  const handlers = useRef({ onError, onDone });
  useEffect(() => {
    handlers.current = { onError, onDone };
  });
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const start = useCallback(async (id: string, url: string, fallbackName: string) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusyId(id);
    setMessage(null);
    try {
      await downloadExcel(url, fallbackName);
      handlers.current.onDone?.();
    } catch (error) {
      if (alive.current && !(isSessionEnded(error) && handlers.current.onError?.(error))) {
        setMessage(downloadErrorMessage(error, userFacingApiError));
      }
    } finally {
      inFlight.current = false;
      if (alive.current) setBusyId(null);
    }
  }, []);

  return { busyId, busy: busyId !== null, message, start };
}

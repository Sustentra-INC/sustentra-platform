"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../../../lib/api";
import {
  RequestActionError,
  SESSION_ENDED,
  createRequest,
  editRequest,
  loadAsks,
  requestActionMessage,
  requestBodyFromDraft,
  resolveRequest,
  sendRequests,
  withdrawRequest,
  type RequestAction,
} from "../api/requests";
import type { Ask, ClientRequest } from "../types/requests";
import { requestsFrom, type AskDraft } from "./requestsStore";

/**
 * The request store in backend mode. Every change goes to the server's request actions
 * (api/requests.ts), and what the server answers is what the screens show: the server decides
 * the state, the number and the history, and records the signed-in user as the person who acted.
 * The store never writes an ask itself, and never rewrites one the server sent.
 */

export interface BackendRequestsStore {
  asks: Ask[];
  requests: ClientRequest[];
  /** Raise a request. Resolves to the ask the server made. */
  saveAsk(draft: AskDraft): Promise<Ask>;
  editAsk(askId: string, whatIsNeeded: string): Promise<void>;
  sendAsks(askIds: string[], lineNumbers?: Record<string, number>): Promise<ClientRequest>;
  resolveAsk(askId: string, resolution?: { link?: string | null; note?: string | null }): Promise<void>;
  withdrawAsk(askId: string, reason: string): Promise<void>;
  /** Replace every ask with ones loaded from the backend (an engagement was opened). */
  replaceAsks(asks: Ask[]): void;
}

/** How long a call may wait for the server. `fetch` has no limit of its own, so without this a
 *  call that never answers would keep its window locked. */
export const REQUEST_TIMEOUT_MS = 30_000;

const NO_ENGAGEMENT = "Create or pick an engagement in Setup before raising requests.";
const BLANK_TEXT = "Write what is needed. The request keeps its earlier text.";
const LONG_TEXT = "Keep what is needed under 2,000 characters.";
const TEXT_MAX = 2000;

/** Runs a call that stops waiting after REQUEST_TIMEOUT_MS: the fetch is aborted, which reads as a
 *  lost connection. */
async function bounded<T>(call: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await call(controller.signal);
  } finally {
    clearTimeout(timer);
  }
}

/** The asks the server returned, over the ones held: a known id is replaced where it stands,
 *  a new one goes at the end. */
function upsert(held: Ask[], returned: Ask[]): Ask[] {
  const next = [...held];
  for (const ask of returned) {
    const at = next.findIndex((a) => a.id === ask.id);
    if (at >= 0) next[at] = ask;
    else next.push(ask);
  }
  return next;
}

const newId = () => `ASK-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

export function useBackendRequestsStore({
  engagementId,
  onSessionEnded,
}: {
  engagementId: string;
  /** Returns true when the error ended the session (it redirects). */
  onSessionEnded?: (error: unknown) => boolean;
}): BackendRequestsStore {
  const [asks, setAsks] = useState<Ask[]>([]);
  const requests = useMemo(() => requestsFrom(asks), [asks]);

  // What an answer that comes back later is compared with: the engagement open now, and the
  // latest handler for an ended session.
  const currentEngagement = useRef(engagementId);
  const sessionEnded = useRef(onSessionEnded);
  useEffect(() => {
    currentEngagement.current = engagementId;
    sessionEnded.current = onSessionEnded;
  });

  const replaceAsks = useCallback((next: Ask[]) => setAsks(next), []);

  // A create that got no answer, and the id it was sent with. The server may have made the request
  // before the connection failed, so the same draft sent again keeps the id: the server then answers
  // "already added" instead of making a second request.
  const unanswered = useRef<{ key: string; id: string } | null>(null);

  /** One action on the server. It acts on the engagement open when it was called, adds the asks the
   *  server returned (only while that engagement is still the open one), and turns a failure into
   *  a RequestActionError whose message is the sentence to show. */
  const perform = useCallback(
    async <T>(
      action: RequestAction,
      call: (engagementId: string, signal: AbortSignal) => Promise<T>,
      asksIn: (result: T) => Ask[]
    ): Promise<T> => {
      const captured = currentEngagement.current;
      if (!captured) throw new RequestActionError(NO_ENGAGEMENT, null);
      const stillOpen = () => currentEngagement.current === captured;

      let result: T;
      try {
        result = await bounded((signal) => call(captured, signal));
      } catch (error) {
        const status = error instanceof ApiError ? error.status : null;
        const ended = sessionEnded.current?.(error) === true;
        if (status === 404 || status === 409) {
          // The request is not as the screen has it: show what the server holds.
          try {
            const held = await bounded((signal) => loadAsks(captured, signal));
            if (stillOpen()) setAsks(held);
          } catch {
            // The reload is a courtesy; the failure below is what matters.
          }
        }
        throw new RequestActionError(ended ? SESSION_ENDED : requestActionMessage(error, action), status);
      }
      if (stillOpen()) {
        const returned = asksIn(result);
        setAsks((held) => upsert(held, returned));
      }
      return result;
    },
    []
  );

  const saveAsk = useCallback(
    (draft: AskDraft): Promise<Ask> => {
      // The same draft in the same engagement, as it would be sent.
      const key = `${currentEngagement.current}|${JSON.stringify(requestBodyFromDraft("", draft))}`;
      const id = unanswered.current?.key === key ? unanswered.current.id : newId();
      const body = requestBodyFromDraft(id, draft);
      return perform("create", (engagement, signal) => createRequest(engagement, body, signal), (ask) => [ask]).then(
        (ask) => {
          unanswered.current = null;
          return ask;
        },
        (error: unknown) => {
          // No answer (status null) leaves it open whether the request was made; any answer settles it.
          unanswered.current = error instanceof RequestActionError && error.status === null ? { key, id } : null;
          throw error;
        }
      );
    },
    [perform]
  );

  const editAsk = useCallback(
    async (askId: string, whatIsNeeded: string): Promise<void> => {
      const text = whatIsNeeded.trim();
      if (!text) throw new RequestActionError(BLANK_TEXT, null);
      if (Array.from(text).length > TEXT_MAX) throw new RequestActionError(LONG_TEXT, null);
      await perform("edit", (id, signal) => editRequest(id, askId, text, signal), (ask) => [ask]);
    },
    [perform]
  );

  const sendAsks = useCallback(
    async (askIds: string[], lineNumbers?: Record<string, number>): Promise<ClientRequest> => {
      const sent = await perform("send", (id, signal) => sendRequests(id, askIds, lineNumbers, signal), (r) => r.asks);
      return { requestNumber: sent.requestNumber, sentAt: sent.sentAt, askIds: sent.askIds };
    },
    [perform]
  );

  const resolveAsk = useCallback(
    async (askId: string, resolution?: { link?: string | null; note?: string | null }): Promise<void> => {
      await perform("resolve", (id, signal) => resolveRequest(id, askId, resolution, signal), (ask) => [ask]);
    },
    [perform]
  );

  const withdrawAsk = useCallback(
    async (askId: string, reason: string): Promise<void> => {
      await perform("withdraw", (id, signal) => withdrawRequest(id, askId, reason, signal), (ask) => [ask]);
    },
    [perform]
  );

  return { asks, requests, saveAsk, editAsk, sendAsks, resolveAsk, withdrawAsk, replaceAsks };
}

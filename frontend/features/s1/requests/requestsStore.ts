"use client";

import { useCallback, useState } from "react";

import type { Ask, AskOrigin, ClientRequest, RequestType } from "../types/requests";

/**
 * The single write path for asks and requests. Fixture-only today; when a
 * backend exists, only the bodies here change. Evidence Workspace, Extraction
 * Review and (next) Evidence Requests all route writes through this store, so
 * the swap is one place.
 */

export interface AskDraft {
  origin?: AskOrigin;
  documentId?: string | null;
  fieldKey?: string | null;
  itemLabel: string;
  facilityName: string | null;
  period: string | null;
  arrival?: string | null;
  sourcePage?: number | null;
  type: RequestType;
  whatIsNeeded: string;
  raisedByName: string;
  raisedByLogin: string;
}

export interface RequestsStore {
  asks: Ask[];
  requests: ClientRequest[];
  /** THE persist function. Creates a not-yet-sent ask. */
  saveAsk: (draft: AskDraft) => Ask;
  /** Edit the "what is needed" text while an ask is still not-yet-sent. */
  editAsk: (askId: string, whatIsNeeded: string) => void;
  /** Bundle checked asks into one request and mark them sent. */
  sendAsks: (askIds: string[]) => ClientRequest;
  resolveAsk: (askId: string, resolution?: { link?: string | null; note?: string | null }) => void;
  withdrawAsk: (askId: string, reason: string) => void;
}

let counter = 0;
const newId = () => `ASK-${Date.now().toString(36)}-${(counter += 1)}`;

export function useRequestsStore(initial: Ask[] = []): RequestsStore {
  const [asks, setAsks] = useState<Ask[]>(initial);
  const [requests, setRequests] = useState<ClientRequest[]>([]);

  const saveAsk = useCallback((draft: AskDraft): Ask => {
    const now = new Date().toISOString();
    const ask: Ask = {
      id: newId(),
      type: draft.type,
      whatIsNeeded: draft.whatIsNeeded,
      source: {
        origin: draft.origin ?? "workspace_document",
        documentId: draft.documentId ?? null,
        fieldKey: draft.fieldKey ?? null,
        itemLabel: draft.itemLabel,
        facilityName: draft.facilityName,
        period: draft.period,
        sourcePage: draft.sourcePage ?? null,
        arrival: draft.arrival ?? null,
      },
      raisedByName: draft.raisedByName,
      raisedByLogin: draft.raisedByLogin,
      raisedAt: now,
      state: "not_yet_sent",
      requestNumber: null,
      lineNumber: null,
      resolution: null,
      withdrawReason: null,
      history: [
        { kind: "raised", actorName: draft.raisedByName, actorLogin: draft.raisedByLogin, at: now },
      ],
    };
    setAsks((cur) => [...cur, ask]);
    return ask;
  }, []);

  const editAsk = useCallback((askId: string, whatIsNeeded: string) => {
    setAsks((cur) =>
      cur.map((a) =>
        a.id === askId && a.state === "not_yet_sent" ? { ...a, whatIsNeeded } : a
      )
    );
  }, []);

  const sendAsks = useCallback((askIds: string[]): ClientRequest => {
    const now = new Date().toISOString();
    let requestNumber = 0;
    setRequests((cur) => {
      requestNumber = cur.length + 1;
      return [...cur, { requestNumber, sentAt: now, askIds }];
    });
    setAsks((cur) =>
      cur.map((a, index) =>
        askIds.includes(a.id)
          ? {
              ...a,
              state: "requested",
              requestNumber: requestNumber || cur.length,
              lineNumber: askIds.indexOf(a.id) + 1,
              history: [
                ...a.history,
                { kind: "sent", actorName: a.raisedByName, actorLogin: a.raisedByLogin, at: now, detail: `request ${requestNumber}` },
              ],
            }
          : a
      )
    );
    return { requestNumber, sentAt: now, askIds };
  }, []);

  const resolveAsk = useCallback((askId: string, resolution?: { link?: string | null; note?: string | null }) => {
    const now = new Date().toISOString();
    setAsks((cur) =>
      cur.map((a) =>
        a.id === askId
          ? {
              ...a,
              state: "resolved",
              resolution: { at: now, by: a.raisedByName, link: resolution?.link ?? null, note: resolution?.note ?? null },
              history: [...a.history, { kind: "resolved", actorName: a.raisedByName, actorLogin: a.raisedByLogin, at: now }],
            }
          : a
      )
    );
  }, []);

  const withdrawAsk = useCallback((askId: string, reason: string) => {
    const now = new Date().toISOString();
    setAsks((cur) =>
      cur.map((a) =>
        a.id === askId
          ? {
              ...a,
              state: "withdrawn",
              withdrawReason: reason,
              history: [...a.history, { kind: "withdrawn", actorName: a.raisedByName, actorLogin: a.raisedByLogin, at: now, detail: reason }],
            }
          : a
      )
    );
  }, []);

  return { asks, requests, saveAsk, editAsk, sendAsks, resolveAsk, withdrawAsk };
}

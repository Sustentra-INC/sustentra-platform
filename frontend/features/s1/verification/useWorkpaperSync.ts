"use client";

import { useEffect, useRef, useState } from "react";

import { loadWorkpaper, saveWorkpaperItem, type WorkpaperKind } from "../api/workpaper";
import type { DocumentDecision } from "../types";
import type { Ask } from "../types/requests";
import type { Examination, Finding } from "../types/verification";

/**
 * Keeps the verifier's findings, examination states and document decisions in the backend:
 * loads them (and the engagement's requests) when an engagement opens, then saves exactly the
 * items that changed. Requests are loaded here but never saved here: the server's request
 * actions are the only way they change. Nothing is saved for an engagement until its own items
 * have loaded, so one engagement's work can never be written into another.
 */
export function useWorkpaperSync({
  enabled,
  engagementId,
  findings,
  examinations,
  documents,
  replaceAsks,
  replaceVerification,
  replaceDocuments,
  onError,
}: {
  enabled: boolean;
  engagementId: string;
  findings: Finding[];
  examinations: Record<string, Examination>;
  documents: Record<string, DocumentDecision>;
  replaceAsks: (asks: Ask[]) => void;
  replaceVerification: (examinations: Record<string, Examination>, findings: Finding[]) => void;
  replaceDocuments: (documents: Record<string, DocumentDecision>) => void;
  /** Called with the failure; the item is retried on its next change. */
  onError: (error: unknown) => void;
}): { loaded: boolean } {
  // What the backend holds, per "kind|id", as JSON: an item is saved only when it differs.
  const saved = useRef<Map<string, string>>(new Map());
  const [readyFor, setReadyFor] = useState<string | null>(null);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  });

  useEffect(() => {
    if (!enabled || !engagementId) return;
    let live = true;
    loadWorkpaper(engagementId)
      .then((loaded) => {
        if (!live) return;
        const snapshot = new Map<string, string>();
        for (const [kind, id, payload] of entries(loaded.findings, loaded.examinations, loaded.documents)) {
          snapshot.set(`${kind}|${id}`, JSON.stringify(payload));
        }
        saved.current = snapshot;
        replaceAsks(loaded.asks);
        replaceVerification(loaded.examinations, loaded.findings);
        replaceDocuments(loaded.documents);
        setReadyFor(engagementId);
      })
      .catch((error: unknown) => {
        if (live) onErrorRef.current(error);
      });
    return () => {
      live = false;
    };
  }, [enabled, engagementId, replaceAsks, replaceVerification, replaceDocuments]);

  useEffect(() => {
    if (!enabled || !engagementId || readyFor !== engagementId) return;
    for (const [kind, id, payload] of entries(findings, examinations, documents)) {
      const key = `${kind}|${id}`;
      const json = JSON.stringify(payload);
      if (saved.current.get(key) === json) continue;
      saved.current.set(key, json);
      saveWorkpaperItem(engagementId, kind, id, payload).catch((error: unknown) => {
        saved.current.delete(key); // not saved: try again on the next change
        onErrorRef.current(error);
      });
    }
  }, [enabled, engagementId, readyFor, findings, examinations, documents]);

  return { loaded: !enabled || readyFor === engagementId };
}

function entries(
  findings: Finding[],
  examinations: Record<string, Examination>,
  documents: Record<string, DocumentDecision>
): [WorkpaperKind, string, object][] {
  return [
    ...findings.map((finding): [WorkpaperKind, string, object] => ["finding", finding.id, finding]),
    ...Object.entries(examinations).map(
      ([dataPointId, examination]): [WorkpaperKind, string, object] => [
        "examination",
        dataPointId,
        { dataPointId, ...examination },
      ]
    ),
    ...Object.values(documents).map((decision): [WorkpaperKind, string, object] => [
      "document",
      decision.documentId,
      decision,
    ]),
  ];
}

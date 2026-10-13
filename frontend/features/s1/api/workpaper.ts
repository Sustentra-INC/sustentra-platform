import { api } from "../../../lib/api";
import type { DocumentDecision } from "../types";
import type { Ask } from "../types/requests";
import type { Examination, Finding } from "../types/verification";

/**
 * The verifier's own work on an engagement, saved in the backend (migration 0012):
 * evidence requests, findings and examination states. One item per object, keyed by
 * its id; saving an item again replaces it.
 */

export type WorkpaperKind = "ask" | "finding" | "examination" | "document";

export interface WorkpaperItem {
  kind: WorkpaperKind;
  item_key: string;
  payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface SavedWorkpaper {
  asks: Ask[];
  findings: Finding[];
  examinations: Record<string, Examination>;
  documents: Record<string, DocumentDecision>;
}

/** Item keys allow letters, digits and : . _ - only. */
export function workpaperKey(id: string): string {
  return id.replace(/[^A-Za-z0-9:._-]/g, "_").slice(0, 200) || "item";
}

export async function loadWorkpaper(engagementId: string): Promise<SavedWorkpaper> {
  const { items } = await api<{ items: WorkpaperItem[] }>(
    `/engagements/${encodeURIComponent(engagementId)}/workpaper-items`
  );
  const saved: SavedWorkpaper = { asks: [], findings: [], examinations: {}, documents: {} };
  for (const item of items) {
    if (item.kind === "ask") saved.asks.push(item.payload as unknown as Ask);
    else if (item.kind === "finding") saved.findings.push(item.payload as unknown as Finding);
    else if (item.kind === "document") {
      const decision = item.payload as unknown as DocumentDecision;
      saved.documents[decision.documentId] = decision;
    } else if (item.kind === "examination") {
      const { dataPointId, ...examination } = item.payload as unknown as Examination & { dataPointId: string };
      saved.examinations[dataPointId] = examination;
    }
  }
  return saved;
}

export function saveWorkpaperItem(
  engagementId: string,
  kind: WorkpaperKind,
  id: string,
  payload: object
): Promise<WorkpaperItem> {
  return api<WorkpaperItem>(
    `/engagements/${encodeURIComponent(engagementId)}/workpaper-items/${kind}/${encodeURIComponent(workpaperKey(id))}`,
    { method: "PUT", body: { payload } }
  );
}

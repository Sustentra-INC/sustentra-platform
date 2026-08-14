import type { EvidenceItem } from "../types";

export function activeEvidenceItems(items: EvidenceItem[]) {
  return items.filter((item) => item.disposition !== "withdrawn");
}

export function workspaceNeeds(items: EvidenceItem[]) {
  const active = activeEvidenceItems(items);
  return {
    type: active.filter((item) => item.typeReviewBand && item.typeReviewBand !== "auto_accepted").length,
    unacceptedTypes: active.filter((item) => item.typeReviewBand === "auto_accepted" && item.detectedType).length,
    facility: active.filter((item) => item.facilityState === "unresolved").length,
    period: active.filter((item) => item.periodState === "unresolved").length,
    blocked: active.filter((item) => item.processingState === "blocked").length,
  };
}

export function selectableEvidenceIds(items: EvidenceItem[]) {
  return items
    .filter((item) => item.disposition !== "withdrawn")
    .map((item) => item.documentId);
}

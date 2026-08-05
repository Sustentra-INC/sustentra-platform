import type { EvidenceItem } from "../types";

export interface EvidenceValidationIssue {
  documentId: string;
  rule: "blocked_reason_required" | "facility_never_blank" | "period_never_blank";
}

export function validateEvidenceItems(items: EvidenceItem[]): EvidenceValidationIssue[] {
  return items.flatMap((item) => {
    const issues: EvidenceValidationIssue[] = [];

    if (item.processingState === "blocked" && !item.haltReason?.trim()) {
      issues.push({ documentId: item.documentId, rule: "blocked_reason_required" });
    }

    if (
      item.facilityState === "resolved" &&
      (!item.facilityId?.trim() || !item.facilityName?.trim())
    ) {
      issues.push({ documentId: item.documentId, rule: "facility_never_blank" });
    }

    if (
      item.periodState === "resolved" &&
      (!item.periodStart?.trim() || !item.periodEnd?.trim())
    ) {
      issues.push({ documentId: item.documentId, rule: "period_never_blank" });
    }

    return issues;
  });
}

export function assertEvidenceItemsValid(items: EvidenceItem[]): void {
  const issues = validateEvidenceItems(items);
  if (issues.length > 0) {
    throw new Error(`S1 evidence validation failed: ${JSON.stringify(issues)}`);
  }
}

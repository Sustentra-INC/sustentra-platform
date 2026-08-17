import type { Finding } from "../types";

export function findingDedupeKey(finding: Pick<Finding, "fieldId" | "type" | "summary">): string {
  return `${finding.fieldId ?? "line"}::${finding.type}::${finding.summary}`;
}


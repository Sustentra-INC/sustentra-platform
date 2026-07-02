import { apiRequest } from "./client";

export function listGapFindings(engagementId: string): Promise<Record<string, unknown>> {
  return apiRequest(`/v1/engagements/${engagementId}/gaps`);
}

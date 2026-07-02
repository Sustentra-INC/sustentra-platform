import { apiRequest } from "./client";
import type { EvidenceRecord } from "../types";

export function getEvidence(evidenceId: string): Promise<EvidenceRecord> {
  return apiRequest<EvidenceRecord>(`/v1/evidence/${evidenceId}`);
}

export function listEngagementEvidence(engagementId: string): Promise<{ items: EvidenceRecord[] }> {
  return apiRequest<{ items: EvidenceRecord[] }>(`/v1/engagements/${engagementId}/evidence`);
}

export function listApprovedEvidence(engagementId: string): Promise<{ items: EvidenceRecord[] }> {
  return apiRequest<{ items: EvidenceRecord[] }>(`/v1/engagements/${engagementId}/approved-evidence`);
}

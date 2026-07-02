import { apiRequest } from "./client";

export interface ReviewPayload {
  candidate_id: string;
  decision: "accepted" | "edited" | "rejected" | "clarification_requested";
  approved_value?: string | number | boolean | null;
  approved_unit?: string | null;
  reviewer_note?: string | null;
  reviewed_by: string;
}

export function submitReviewDecision(
  evidenceId: string,
  fieldName: string,
  payload: ReviewPayload
): Promise<Record<string, unknown>> {
  return apiRequest(`/v1/evidence/${evidenceId}/fields/${fieldName}/review`, {
    method: "PUT",
    body: JSON.stringify(payload)
  });
}

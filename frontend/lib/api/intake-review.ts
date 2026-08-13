import { intakeRequest } from "./intake";
import type { EscalationDetail, ResolveResult, ReviewQueue } from "../intake-types";

/**
 * The internal review queue (Phase D2).
 *
 * Separate from lib/api/review.ts, which belongs to the S1 evidence review
 * surface and is untouched. These three calls are the reviewer half of intake:
 * see what is waiting, open one, answer it.
 *
 * Every route behind these is restricted to the sustentra_reviewer role, so a
 * client signing in and guessing the URL gets a 403 from the API, not just a
 * missing link in the UI.
 */

export function getReviewQueue(): Promise<ReviewQueue> {
  return intakeRequest<ReviewQueue>("/v1/intake/review/queue");
}

export function getEscalation(escalationId: string): Promise<EscalationDetail> {
  return intakeRequest<EscalationDetail>(
    `/v1/intake/review/escalations/${encodeURIComponent(escalationId)}`
  );
}

export function resolveEscalation(
  escalationId: string,
  payload: { value: Record<string, unknown>; resolution_note?: string }
): Promise<ResolveResult> {
  return intakeRequest<ResolveResult>(
    `/v1/intake/review/escalations/${encodeURIComponent(escalationId)}/resolve`,
    { method: "POST", body: payload }
  );
}

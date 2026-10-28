import { api } from "../../../lib/api";
import { userFacingApiError } from "./s1Backend";

/**
 * Processing runs: asking for a document to be read, and following the read
 * (contracts/processing_run.schema.json). With the API in inline mode the read finishes in
 * the request (200); queued, the run comes back still waiting (202) and the workspace polls
 * the engagement's runs until it finishes.
 */

export type ProcessingRunStatus = "queued" | "in_progress" | "completed" | "failed";

export interface ProcessingRunView {
  run_id: string;
  document_id: string;
  engagement_id: string;
  evidence_id: string | null;
  status: ProcessingRunStatus;
  created_at?: string;
  started_at: string | null;
  completed_at: string | null;
  pipeline_version: string;
  requested_by?: string;
  attempt?: number;
  max_attempts?: number;
  canonical_type_id_override?: string | null;
  pipeline_run_id?: string | null;
  error_code?: string | null;
  error: string | null;
}

/** Shown when a read failed without a sentence of its own. */
export const READ_FAILED_ON_OUR_SIDE = "Reading failed on our side. Try again; if it happens again, tell us.";

/** A run that is waiting to be read or being read now. */
export function isActiveRun(run: Pick<ProcessingRunView, "status">): boolean {
  return run.status === "queued" || run.status === "in_progress";
}

/** Ask for a document to be read. With a type, it is read as that type instead of the
 *  classifier's guess (the reviewer set it). Both 200 (read in the request) and 202 (queued)
 *  resolve to the run. */
export function requestRead(documentId: string, canonicalTypeIdOverride?: string): Promise<ProcessingRunView> {
  return api<ProcessingRunView>(`/documents/${encodeURIComponent(documentId)}/processing-runs`, {
    method: "POST",
    body: canonicalTypeIdOverride ? { canonical_type_id_override: canonicalTypeIdOverride } : {},
  });
}

/** Each document's latest run in the engagement: the one call the workspace polls. */
export async function listProcessingRuns(engagementId: string): Promise<ProcessingRunView[]> {
  const result = await api<{ items: ProcessingRunView[] }>(
    `/engagements/${encodeURIComponent(engagementId)}/processing-runs`
  );
  return result.items;
}

/** What to tell the user about a failed run (same wording as a failed read in the request). */
export function readFailureMessage(run: Pick<ProcessingRunView, "error">): string {
  return userFacingApiError(new Error(run.error || READ_FAILED_ON_OUR_SIDE));
}

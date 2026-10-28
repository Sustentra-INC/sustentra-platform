import type { BackendDocumentLike } from "../adapters/evidenceAdapter";
import { isActiveRun, readFailureMessage, requestRead, type ProcessingRunView } from "../api/processingRuns";
import type { EvidenceItem } from "../types";

/** Run failures whose message names the problem better than the document's halt mapping. */
export const RUN_MESSAGE_CODES = ["timed_out", "worker_error", "file_missing", "document_missing"] as const;

/**
 * Lays each document's latest processing run over its evidence row (backend mode): a run that
 * is waiting or being read marks the row `reading`, and a blocked row whose run failed in one
 * of the ways above says why in the run's own words. Anything else comes back untouched, and
 * the same array comes back when nothing changed.
 */
export function withReadingState(items: EvidenceItem[], runs: Record<string, ProcessingRunView>): EvidenceItem[] {
  if (Object.keys(runs).length === 0) return items;
  let changed = false;
  const next = items.map((item) => {
    const run = runs[item.documentId];
    if (!run) return item;
    if (run.status === "queued" || run.status === "in_progress") {
      changed = true;
      return { ...item, reading: run.status };
    }
    if (
      item.processingState === "blocked" &&
      run.status === "failed" &&
      (RUN_MESSAGE_CODES as readonly string[]).includes(run.error_code ?? "")
    ) {
      changed = true;
      return { ...item, haltReason: readFailureMessage(run) };
    }
    return item;
  });
  return changed ? next : items;
}

/** How a freshly uploaded document's read stands. */
export type ReadStart =
  | { kind: "reading"; run: ProcessingRunView }
  | { kind: "done"; run: ProcessingRunView }
  | { kind: "failed"; reason: string };

/**
 * After an upload: where the read of the document stands. The upload response carries the run
 * when the API queued the read; otherwise the read is asked for now (inline, that is the read
 * itself). A request that throws propagates to the caller.
 */
export async function readAfterUpload(
  document: BackendDocumentLike,
  request: (documentId: string) => Promise<ProcessingRunView> = requestRead
): Promise<ReadStart> {
  const run = document.processing_run ?? (await request(document.document_id));
  if (isActiveRun(run)) return { kind: "reading", run };
  if (run.status === "completed") return { kind: "done", run };
  return { kind: "failed", reason: `Uploaded, but could not be read: ${readFailureMessage(run)}` };
}

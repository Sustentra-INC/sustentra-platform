import { api } from "../../../lib/api";

/**
 * Document batches: files uploaded together share one batch, and one call says how reading
 * them stands (docs/api_contract.md, "Document batches"). The API counts and words everything;
 * nothing here adds up or builds text.
 */

export type BatchDocumentStatus = "queued" | "reading" | "done" | "partial" | "failed" | "not_started";

export interface BatchChunks {
  total: number;
  completed: number;
  failed: number;
  failed_pages: [number, number][];
}

export interface BatchDocument {
  document_id: string;
  file_name: string;
  status: BatchDocumentStatus;
  /** Set when a large PDF is read in page chunks. */
  chunks: BatchChunks | null;
  canonical_type_id: string | null;
  /** A sentence saying why the document was not read in full; null when nothing went wrong. */
  halt_reason: string | null;
  records_found: number;
}

export interface BatchView {
  batch_id: string;
  engagement_id: string;
  label: string | null;
  items: BatchDocument[];
  totals: Record<BatchDocumentStatus, number>;
  /** Nothing is waiting or being read any more (a file no read was asked for does not count): the client stops asking. */
  complete: boolean;
}

export const BATCH_POLL_MS = 3000;

export async function createDocumentBatch(engagementId: string, label?: string): Promise<string> {
  const created = await api<{ batch_id: string }>(`/engagements/${encodeURIComponent(engagementId)}/document-batches`, {
    method: "POST",
    body: label ? { label } : {},
  });
  return created.batch_id;
}

export function getDocumentBatch(engagementId: string, batchId: string): Promise<BatchView> {
  return api<BatchView>(
    `/engagements/${encodeURIComponent(engagementId)}/document-batches/${encodeURIComponent(batchId)}`
  );
}

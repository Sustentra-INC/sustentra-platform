import type { BatchDocument, BatchDocumentStatus, BatchView } from "../api/documentBatches";
import { plainBatchHalt, resolveCanonicalTypeDisplayName } from "../adapters/evidenceAdapter";
import type { EvidenceItem } from "../types";
import { BreakableName } from "./BreakableName";

/** Words for each status, and the state colour that goes with the word (never colour alone). */
export const BATCH_STATUS: Record<BatchDocumentStatus, { label: string; role: string }> = {
  queued: { label: "Waiting", role: "active" },
  reading: { label: "Reading", role: "active" },
  done: { label: "Done", role: "resolved" },
  partial: { label: "Partly read", role: "open" },
  failed: { label: "Couldn't read", role: "blocking" },
  not_started: { label: "Not started", role: "open" },
};

/** What the row says. A document read in part that gave no values at all was not read. */
export function batchStatusFor(item: Pick<BatchDocument, "status" | "records_found">): { label: string; role: string } {
  if (item.status === "partial" && item.records_found === 0) return { label: "Not read", role: "open" };
  return BATCH_STATUS[item.status];
}

const ORDER: BatchDocumentStatus[] = ["queued", "reading", "done", "partial", "failed", "not_started"];

/** What a large PDF's reading has got through; nothing for a document read whole. */
function progressText(item: BatchDocument): string | null {
  const chunks = item.chunks;
  if (!chunks || item.status === "queued") return null;
  return `${chunks.completed} of ${chunks.total} parts read${chunks.failed ? `, ${chunks.failed} failed` : ""}`;
}

/**
 * One compact table for a batch of uploads: a row per file with where its reading stands, what it
 * was recognised as, how many records were found and, when it was not read in full, why. A file
 * that has been read opens its extraction review. The API supplies every count and sentence.
 */
export function BatchProgress({
  batch,
  onOpenDocument,
  items = [],
}: {
  batch: BatchView;
  onOpenDocument: (documentId: string) => void;
  /** The engagement's documents: their halt reason is mapped from the pipeline's code, so it is preferred. */
  items?: EvidenceItem[];
}) {
  const halts = new Map(items.map((i) => [i.documentId, i.haltReason]));
  // Totals follow the row labels, so "Partly read" counts only documents that gave some values.
  const counts = new Map<string, number>();
  for (const item of batch.items) {
    const label = batchStatusFor(item).label;
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  const totals = [...ORDER.map((status) => BATCH_STATUS[status].label), "Not read"].filter(
    (label) => (counts.get(label) ?? 0) > 0
  );
  return (
    <div className="s1-batch" aria-live="polite">
      <div className="s1-batch__head">
        <strong>Reading this batch</strong>
        <span className="s1-muted">
          {totals.map((label) => `${counts.get(label)} ${label.toLowerCase()}`).join(" · ")}
        </span>
      </div>
      <table className="s1-batch__table">
        <thead>
          <tr>
            <th scope="col">File</th>
            <th scope="col">Status</th>
            <th scope="col">Type</th>
            <th scope="col" className="s1-batch__num">
              Records
            </th>
          </tr>
        </thead>
        <tbody>
          {batch.items.map((item) => {
            const status = batchStatusFor(item);
            const progress = progressText(item);
            const type = item.canonical_type_id
              ? resolveCanonicalTypeDisplayName({ canonical_type_id: item.canonical_type_id })
              : null;
            const note = halts.get(item.document_id) || plainBatchHalt(item.halt_reason);
            return (
              <tr key={item.document_id} className="s1-batch__row">
                <td className="s1-batch__file">
                  {item.status === "queued" || item.status === "reading" ? (
                    <BreakableName name={item.file_name} />
                  ) : (
                    <button className="s1-linklike" type="button" onClick={() => onOpenDocument(item.document_id)}>
                      <BreakableName name={item.file_name} />
                    </button>
                  )}
                  {note ? <span className="s1-batch__note">{note}</span> : null}
                </td>
                <td>
                  <span className={`s1-state s1-state--${status.role}`}>{status.label}</span>
                  {progress ? <span className="s1-muted s1-batch__progress">{progress}</span> : null}
                </td>
                <td className="s1-muted">{type ?? "–"}</td>
                <td className="s1-batch__num">{item.status === "queued" || item.status === "reading" || item.status === "not_started" ? "–" : item.records_found}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

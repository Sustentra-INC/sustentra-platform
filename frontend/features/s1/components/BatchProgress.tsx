import type { BatchDocument, BatchDocumentStatus, BatchView } from "../api/documentBatches";
import { resolveCanonicalTypeDisplayName } from "../adapters/evidenceAdapter";

/** Words for each status, and the state colour that goes with the word (never colour alone). */
export const BATCH_STATUS: Record<BatchDocumentStatus, { label: string; role: string }> = {
  queued: { label: "Waiting", role: "active" },
  reading: { label: "Reading", role: "active" },
  done: { label: "Done", role: "resolved" },
  partial: { label: "Partly read", role: "open" },
  failed: { label: "Couldn't read", role: "blocking" },
};

const ORDER: BatchDocumentStatus[] = ["queued", "reading", "done", "partial", "failed"];

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
}: {
  batch: BatchView;
  onOpenDocument: (documentId: string) => void;
}) {
  const totals = ORDER.filter((status) => batch.totals[status] > 0);
  return (
    <div className="s1-batch" aria-live="polite">
      <div className="s1-batch__head">
        <strong>Reading this batch</strong>
        <span className="s1-muted">
          {totals.map((status) => `${batch.totals[status]} ${BATCH_STATUS[status].label.toLowerCase()}`).join(" · ")}
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
            const status = BATCH_STATUS[item.status];
            const progress = progressText(item);
            const type = item.canonical_type_id
              ? resolveCanonicalTypeDisplayName({ canonical_type_id: item.canonical_type_id })
              : null;
            const note = item.halt_reason;
            return (
              <tr key={item.document_id} className="s1-batch__row">
                <td className="s1-batch__file">
                  {item.status === "queued" || item.status === "reading" ? (
                    item.file_name
                  ) : (
                    <button className="s1-linklike" type="button" onClick={() => onOpenDocument(item.document_id)}>
                      {item.file_name}
                    </button>
                  )}
                  {note ? <span className="s1-batch__note">{note}</span> : null}
                </td>
                <td>
                  <span className={`s1-state s1-state--${status.role}`}>{status.label}</span>
                  {progress ? <span className="s1-muted s1-batch__progress">{progress}</span> : null}
                </td>
                <td className="s1-muted">{type ?? "–"}</td>
                <td className="s1-batch__num">{item.status === "queued" || item.status === "reading" ? "–" : item.records_found}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

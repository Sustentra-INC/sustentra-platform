import type { BatchDocument, BatchDocumentStatus, BatchView } from "../api/documentBatches";
import { resolveCanonicalTypeDisplayName } from "../adapters/evidenceAdapter";

/** Words for each status, and the state colour that goes with the word (never colour alone). */
export const BATCH_STATUS: Record<BatchDocumentStatus, { label: string; role: string }> = {
  queued: { label: "Waiting", role: "active" },
  reading: { label: "Reading", role: "active" },
  done: { label: "Done", role: "resolved" },
  partial: { label: "Partly read", role: "open" },
  failed: { label: "Couldn't read", role: "blocking" },
  not_started: { label: "Not started", role: "open" },
};

const TOTAL_ORDER: BatchDocumentStatus[] = ["queued", "reading", "done", "partial", "failed", "not_started"];
const TOTAL_LABELS: Record<BatchDocumentStatus, string> = {
  queued: "waiting",
  reading: "reading",
  done: "done",
  partial: "partly read",
  failed: "couldn't read",
  not_started: "not started",
};

/** What a large PDF's reading has got through; nothing for a document read whole. */
function progressText(item: BatchDocument): string | null {
  const chunks = item.chunks;
  if (!chunks || item.status === "queued") return null;
  return `${chunks.completed} of ${chunks.total} parts read${chunks.failed ? `, ${chunks.failed} failed` : ""}`;
}

/** Fraction complete (0–100) for a file being read in chunks; null otherwise. */
function chunkPct(item: BatchDocument): number | null {
  if (item.status !== "reading" || !item.chunks || item.chunks.total === 0) return null;
  return Math.round((item.chunks.completed / item.chunks.total) * 100);
}

/** Normalise a filename extension to a chip key. */
function batchFileExt(name: string): string {
  const parts = name.split(".");
  if (parts.length < 2) return "file";
  const ext = parts.pop()!.toLowerCase();
  if (ext === "jpeg") return "jpg";
  if (ext === "doc") return "docx";
  if (ext === "xls") return "xlsx";
  return ext;
}

/**
 * Card rows for a batch of uploads: one row per file showing its reading status, recognised
 * type, and an inline progress bar while it is being read. The API supplies every sentence.
 */
export function BatchProgress({
  batch,
  onOpenDocument,
}: {
  batch: BatchView;
  onOpenDocument: (documentId: string) => void;
}) {
  const totals = TOTAL_ORDER
    .filter((k) => batch.totals[k] > 0)
    .map((k) => `${batch.totals[k]} ${TOTAL_LABELS[k]}`)
    .join(" · ");

  return (
    <div className="s1-batch" aria-live="polite" role="table">
      <div role="row" className="s1-sr-only">
        <span role="columnheader">File</span>
        <span role="columnheader">Status</span>
        <span role="columnheader">Type</span>
        <span role="columnheader">Records</span>
      </div>
      {batch.items.map((item) => {
        const status = BATCH_STATUS[item.status];
        const type = item.canonical_type_id
          ? resolveCanonicalTypeDisplayName({ canonical_type_id: item.canonical_type_id })
          : null;
        const progress = progressText(item);
        const pct = chunkPct(item);
        const ext = batchFileExt(item.file_name);
        const canOpen = item.status !== "queued" && item.status !== "reading";
        const subLine = item.halt_reason ?? type ?? progress;

        return (
          <div key={item.document_id} className="s1-batch__row" role="row">
            <span aria-hidden="true" className={`s1-batch__tag s1-batch__tag--${ext}`}>
              {ext.toUpperCase()}
            </span>
            <span className="s1-batch__info">
              {canOpen ? (
                <button
                  className="s1-linklike s1-batch__name"
                  type="button"
                  onClick={() => onOpenDocument(item.document_id)}
                >
                  {item.file_name}
                </button>
              ) : (
                <span className="s1-batch__name">{item.file_name}</span>
              )}
              {subLine ? <span className="s1-batch__sub">{subLine}</span> : null}
            </span>
            {item.records_found > 0 ? (
              <span className="s1-batch__records" aria-label={`${item.records_found} records`}>
                {item.records_found}
              </span>
            ) : null}
            {item.status === "reading" ? (
              <span className="s1-batch__mini" aria-hidden="true">
                <span className="s1-batch__mini-fill" style={{ width: `${pct ?? 0}%` }} />
              </span>
            ) : null}
            <span className={`s1-state s1-state--${status.role}`}>{status.label}</span>
          </div>
        );
      })}
      {totals ? <div className="s1-batch__totals">{totals}</div> : null}
    </div>
  );
}

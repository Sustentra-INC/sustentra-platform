"use client";

import { useEffect, useState } from "react";

import { userFacingApiError } from "../api/s1Backend";
import { listWorkpaperCopies, workpaperCopyHref, type WorkpaperCopy } from "../api/workpaperCopies";

const FIRST = 3; // the report below stays in view; the rest is one click away
const PAGE = 10;
const MOST = 100; // the API gives at most this many
const FINGERPRINT_TITLE =
  "A code that identifies this exact file (its SHA-256). A file with the same code is the same file. Hover a code to see all of it.";

function when(iso: string | null): string {
  const date = iso ? new Date(iso) : null;
  if (!date || Number.isNaN(date.getTime())) return iso ?? "";
  return date.toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}

function size(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * Every workpaper downloaded for this engagement is kept as it was. This lists them, newest first, so what
 * the figures were on the day a file was sent can be fetched again. `refreshKey` changes after a download.
 */
export function SavedCopies({
  engagementId,
  refreshKey,
  busyId,
  onDownload,
}: {
  engagementId: string;
  refreshKey: number;
  /** The download in progress (a copy's id, or "live" for the button above): no other can start. */
  busyId: string | null;
  onDownload: (copyId: string, url: string) => void;
}) {
  const [state, setState] = useState<{ key: string; items: WorkpaperCopy[]; total: number } | null>(null);
  const [limit, setLimit] = useState(FIRST);
  const [error, setError] = useState<string | null>(null);
  const key = `${engagementId}:${refreshKey}:${limit}`;

  useEffect(() => {
    let live = true;
    listWorkpaperCopies(engagementId, limit)
      .then((page) => {
        if (!live) return;
        setError(null);
        setState({ key, items: page.items, total: page.total });
      })
      .catch((caught: unknown) => {
        if (live) setError(userFacingApiError(caught));
      });
    return () => {
      live = false;
    };
  }, [engagementId, limit, key]);

  const mine = state && state.key.startsWith(`${engagementId}:`) ? state : null;
  return (
    <section className="s1-out-section s1-out-saved" aria-label="Saved copies">
      <h3>Saved copies</h3>
      {error ? (
        <p className="s1-muted">Could not load the saved copies. {error}</p>
      ) : !mine ? (
        <p className="s1-muted">Loading…</p>
      ) : mine.items.length === 0 ? (
        <p className="s1-muted">Each workpaper you download is saved here.</p>
      ) : (
        <>
          <div className="s1-table-wrap s1-out-tablewrap">
            <table className="s1-table s1-out-table">
              <thead>
                <tr>
                  <th>Saved</th>
                  <th>By</th>
                  <th className="s1-out-num s1-out-hide-narrow">Size</th>
                  <th className="s1-out-hide-narrow" title={FINGERPRINT_TITLE}>
                    Fingerprint
                  </th>
                  <th>
                    <span className="s1-sr-only">Download</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {mine.items.map((copy) => (
                  <tr key={copy.id}>
                    <td>{when(copy.created_at)}</td>
                    <td className="s1-out-saved__by" title={copy.prepared_by ?? undefined}>
                      {copy.prepared_by ?? "Unknown"}
                    </td>
                    <td className="s1-out-num s1-out-hide-narrow">{size(copy.size_bytes)}</td>
                    <td className="s1-out-hide-narrow s1-num" title={copy.sha256}>
                      {copy.sha256.slice(0, 12)}
                    </td>
                    <td className="s1-out-num">
                      <button
                        className="s1-linklike"
                        type="button"
                        disabled={busyId !== null}
                        aria-busy={busyId === copy.id}
                        onClick={() => onDownload(copy.id, workpaperCopyHref(engagementId, copy.id))}
                      >
                        {busyId === copy.id ? "Preparing…" : "Download"}
                        <span className="s1-sr-only"> the copy saved {when(copy.created_at)}</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {mine.total > mine.items.length && limit < MOST ? (
            <button className="s1-linklike" type="button" onClick={() => setLimit((n) => Math.min(n + PAGE, MOST))}>
              Show older copies ({mine.total - mine.items.length} more)
            </button>
          ) : mine.total > mine.items.length ? (
            <p className="s1-muted">The newest {MOST} are shown.</p>
          ) : null}
        </>
      )}
    </section>
  );
}

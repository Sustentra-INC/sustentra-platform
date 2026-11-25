"use client";

import { useEffect, useState } from "react";

import { userFacingApiError } from "../api/s1Backend";
import { listWorkpaperCopies, workpaperCopyHref, type WorkpaperCopy } from "../api/workpaperCopies";

const PAGE = 10;
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
export function SavedCopies({ engagementId, refreshKey }: { engagementId: string; refreshKey: number }) {
  const [state, setState] = useState<{ key: string; items: WorkpaperCopy[]; total: number } | null>(null);
  const [limit, setLimit] = useState(PAGE);
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
                  <th className="s1-out-num">Size</th>
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
                    <td>{copy.prepared_by ?? "Unknown"}</td>
                    <td className="s1-out-num">{size(copy.size_bytes)}</td>
                    <td className="s1-out-hide-narrow s1-num" title={copy.sha256}>
                      {copy.sha256.slice(0, 12)}
                    </td>
                    <td className="s1-out-num">
                      <a className="s1-linklike" href={workpaperCopyHref(engagementId, copy.id)} download>
                        Download
                        <span className="s1-sr-only"> the copy saved {when(copy.created_at)}</span>
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {mine.total > mine.items.length ? (
            <button className="s1-linklike" type="button" onClick={() => setLimit((n) => n + PAGE)}>
              Show older copies ({mine.total - mine.items.length} more)
            </button>
          ) : null}
        </>
      )}
    </section>
  );
}

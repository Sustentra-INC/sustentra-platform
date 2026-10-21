"use client";

import { useEffect, useRef, useState } from "react";

import { api, apiPath } from "../../../lib/api";
import type { PageMark, ReviewSpan } from "../types/review";

/**
 * The uploaded document's page as an image, with the extracted value outlined at the
 * position the extractor recorded. Opens at the value's page; the reviewer can page
 * through the rest. Works the same in every browser (a framed PDF cannot be drawn over).
 *
 * Every other value read from the page is drawn as a faint box too: clicking one selects
 * that value, so the reviewer can go from the document to the value as well as back.
 */
export function BackendPageView({
  documentId,
  span,
  marks = [],
  onPickMark,
}: {
  documentId: string;
  span: ReviewSpan | null;
  marks?: PageMark[];
  onPickMark?: (mark: PageMark) => void;
}) {
  const [pages, setPages] = useState<number | null>(null);
  const [page, setPage] = useState(span?.page ?? 1);
  const [failed, setFailed] = useState(false);
  const mark = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let live = true;
    api<{ pages: number }>(`/documents/${encodeURIComponent(documentId)}/pages`)
      .then((body) => {
        if (live) setPages(body.pages);
      })
      .catch(() => {
        if (live) setFailed(true);
      });
    return () => {
      live = false;
    };
  }, [documentId]);

  const onThisPage = span && span.page === page;
  const src = apiPath(`/documents/${encodeURIComponent(documentId)}/pages/${page}/image`);

  if (failed) {
    return (
      <div className="s1-xr-fallback">
        This file has no page view. <a href={apiPath(`/documents/${encodeURIComponent(documentId)}/download`)}>Download it</a>{" "}
        to check the value.
      </div>
    );
  }

  return (
    <div className="s1-pv">
      <div className="s1-pv__bar">
        <button
          className="s1-button s1-button--compact"
          type="button"
          aria-label="Previous page"
          disabled={page <= 1}
          onClick={() => setPage((p) => Math.max(1, p - 1))}
        >
          ‹
        </button>
        <span className="s1-mono s1-muted">
          page {page} of {pages ?? "…"}
        </span>
        <button
          className="s1-button s1-button--compact"
          type="button"
          aria-label="Next page"
          disabled={pages !== null && page >= pages}
          onClick={() => setPage((p) => (pages ? Math.min(pages, p + 1) : p + 1))}
        >
          ›
        </button>
        {span && !onThisPage ? (
          <button className="s1-linklike" type="button" onClick={() => setPage(span.page)}>
            Go to the value (page {span.page})
          </button>
        ) : null}
        {pages !== null && pages > 2 ? (
          <label className="s1-pv__goto">
            Go to page
            <input
              type="number"
              min={1}
              max={pages}
              defaultValue={page}
              key={page}
              onKeyDown={(e) => {
                if (e.key !== "Enter") return;
                const n = Number((e.target as HTMLInputElement).value);
                if (Number.isInteger(n) && n >= 1 && n <= pages) setPage(n);
              }}
            />
          </label>
        ) : null}
        <a
          className="s1-linklike s1-pv__open"
          href={apiPath(`/documents/${encodeURIComponent(documentId)}/preview`)}
          target="_blank"
          rel="noreferrer"
        >
          Open original
        </a>
      </div>
      {valuePages(marks).length > 1 ? (
        <div className="s1-pv__pages" role="group" aria-label="Pages with values">
          <span>Values on</span>
          {valuePages(marks).map((n) => (
            <button
              key={n}
              className={`s1-pv__pagechip${n === page ? " is-on" : ""}`}
              type="button"
              aria-pressed={n === page}
              onClick={() => setPage(n)}
            >
              p.{n}
            </button>
          ))}
        </div>
      ) : null}
      <div className="s1-pv__page">
        {/* eslint-disable-next-line @next/next/no-img-element -- an authenticated API image, not a static asset */}
        <img
          className="s1-pv__img"
          src={src}
          alt={`Page ${page} of the uploaded document`}
          onLoad={() => mark.current?.scrollIntoView({ block: "center", behavior: "smooth" })}
        />
        {onPickMark
          ? boxesOnPage(marks, page).map((group) => {
              const [first] = group;
              const labels = group.map((m) => m.label).join(" · ");
              return (
                <button
                  key={first.id}
                  type="button"
                  className={`s1-pv__box s1-pv__box--${first.reviewState}`}
                  style={{
                    left: `${first.span.x * 100}%`,
                    top: `${first.span.y * 100}%`,
                    width: `${first.span.w * 100}%`,
                    height: `${first.span.h * 100}%`,
                  }}
                  title={labels}
                  aria-label={`Select ${labels}`}
                  onClick={() => onPickMark(first)}
                />
              );
            })
          : null}
        {onThisPage ? (
          <div
            ref={mark}
            className="s1-pv__mark"
            style={{
              left: `${span.x * 100}%`,
              top: `${span.y * 100}%`,
              width: `${span.w * 100}%`,
              height: `${span.h * 100}%`,
            }}
            aria-label="The extracted value"
          />
        ) : null}
      </div>
      {!span ? <p className="s1-muted s1-pv__note">The value&rsquo;s position was not recorded; check it on the page.</p> : null}
    </div>
  );
}

/** The values on one page, one box per position: values read from the same line (an amount
 *  and its unit) share a box, so the box is drawn once and a click selects the first of them
 *  (clicking again moves to the next). */
function boxesOnPage(marks: PageMark[], page: number): (PageMark & { span: ReviewSpan })[][] {
  const groups = new Map<string, (PageMark & { span: ReviewSpan })[]>();
  for (const m of marks) {
    const span = m.span;
    if (!span || span.page !== page) continue;
    const key = [span.x, span.y, span.w, span.h].map((n) => n.toFixed(3)).join("|");
    groups.set(key, [...(groups.get(key) ?? []), { ...m, span }]);
  }
  return Array.from(groups.values());
}

/** The pages that hold at least one value read from the document, in order. */
function valuePages(marks: PageMark[] | undefined): number[] {
  const pages = new Set<number>();
  for (const mark of marks ?? []) if (mark.span?.page) pages.add(mark.span.page);
  return [...pages].sort((a, b) => a - b);
}

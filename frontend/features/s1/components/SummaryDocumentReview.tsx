"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { userFacingApiError } from "../api/s1Backend";
import {
  getDocumentLocations,
  getMethodologyReview,
  prefillMethodology,
  type MethodologyReviewData,
  type QuoteLocation,
  type SourceAt,
} from "../api/methodologyReview";
import type { PageMark, ReviewSpan, ValueReviewState } from "../types/review";
import { aiStatusWords, FieldRow } from "./BackendMethodologyReview";

/**
 * A company summary document (a GHG statement, a management assertion, the inventory workbook)
 * opened on its own: the page with a highlight where each methodology fact was read, and the
 * facts beside it with Accept, Edit and Reject. The facts are Methodology review's own records:
 * every action here is the same call Methodology review makes, so a decision made on either
 * screen is the one decision. Nothing is copied.
 *
 * A quote is highlighted only where the PDF's own text holds it (the server finds it); a quote
 * that is not found on its page says so, and the page still opens where the source cites.
 */

export interface SummaryViewerProps {
  /** The page to open at (the selected quote's, or the cited one when the quote was not located). */
  page: number | null;
  /** The first box of the selected quote, or null when it has none. */
  span: ReviewSpan | null;
  marks: PageMark[];
  /** Every box of the selected quote. */
  selectedMarkIds: string[];
  /** "Quote not located on this page" when the selected quote has no highlight. */
  pageNote: string | null;
  onPickMark: (mark: PageMark) => void;
  /** Changes with the selection, so a viewer can open again at the new page. */
  viewerKey: string;
}

const NOT_LOCATED = "Quote not located";
const NOT_LOCATED_ON_PAGE = "Quote not located on this page";

const markId = (fieldId: string, entry: number | null, index: number) => `${fieldId}#${entry ?? ""}#${index}`;
const locKey = (fieldId: string, entry: number | null) => `${fieldId}|${entry ?? ""}`;

function reviewState(status: string | undefined): ValueReviewState {
  if (status === "accepted") return "accepted";
  if (status === "edited") return "corrected";
  return "to_review";
}

export function SummaryDocumentReview({
  engagementId,
  documentId,
  fileName,
  at,
  backLabel,
  onBack,
  onError,
  renderViewer,
}: {
  engagementId: string;
  documentId: string;
  fileName?: string;
  /** Opened from a methodology source: the field and quote to select, and the page it cites. */
  at?: { fieldId?: string; entry?: number; page?: number };
  backLabel: string;
  onBack: () => void;
  onError?: (error: unknown) => boolean;
  renderViewer: (props: SummaryViewerProps) => ReactNode;
}) {
  const [data, setData] = useState<MethodologyReviewData | null>(null);
  const [locations, setLocations] = useState<QuoteLocation[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState<{ fieldId: string; entry: number | null } | null>(
    at?.fieldId ? { fieldId: at.fieldId, entry: at.entry ?? null } : null
  );
  const [citedPage, setCitedPage] = useState<number | null>(at?.page ?? null);
  const prefillRunning = useRef(false);
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  });

  const load = useCallback(async () => {
    try {
      const [review, found] = await Promise.all([getMethodologyReview(engagementId), getDocumentLocations(engagementId, documentId)]);
      setData(review);
      setLocations(found);
      setLoadError(null);
    } catch (error) {
      if (onErrorRef.current?.(error)) return;
      setLoadError(userFacingApiError(error));
    }
  }, [engagementId, documentId]);

  useEffect(() => {
    let live = true;
    Promise.all([getMethodologyReview(engagementId), getDocumentLocations(engagementId, documentId)])
      .then(([review, found]) => {
        if (!live) return;
        setData(review);
        setLocations(found);
        setLoadError(null);
      })
      .catch((error: unknown) => {
        if (!live || onErrorRef.current?.(error)) return;
        setLoadError(userFacingApiError(error));
      });
    return () => {
      live = false;
    };
  }, [engagementId, documentId]);

  async function act(run: () => Promise<unknown>) {
    setBusy(true);
    setNotice(null);
    try {
      await run();
      await load();
    } catch (error) {
      if (!onError?.(error)) {
        setNotice(userFacingApiError(error));
        await load();
      }
    } finally {
      setBusy(false);
    }
  }

  async function readWithAi() {
    if (prefillRunning.current) return;
    prefillRunning.current = true;
    await act(() => prefillMethodology(engagementId));
    prefillRunning.current = false;
  }

  const records = useMemo(() => new Map((data?.fields ?? []).map((r) => [r.fieldId, r])), [data]);
  const byKey = useMemo(() => new Map((locations ?? []).map((l) => [locKey(l.fieldId, l.entry), l])), [locations]);
  const fieldIds = useMemo(() => new Set((locations ?? []).map((l) => l.fieldId)), [locations]);
  const groups = useMemo(
    () =>
      (data?.groups ?? [])
        .map((g) => ({ ...g, defs: (data?.catalog ?? []).filter((d) => d.group === g.group && fieldIds.has(d.fieldId) && records.has(d.fieldId)) }))
        .filter((g) => g.defs.length > 0),
    [data, fieldIds, records]
  );

  const marks = useMemo<PageMark[]>(() => {
    const label = new Map((data?.catalog ?? []).map((d) => [d.fieldId, d.label]));
    return (locations ?? []).flatMap((l) =>
      l.located && l.page
        ? l.rects.map((r, i) => ({
            id: markId(l.fieldId, l.entry, i),
            span: { page: l.page as number, ...r },
            label: label.get(l.fieldId) ?? l.fieldId,
            reviewState: reviewState(records.get(l.fieldId)?.decision?.status),
          }))
        : []
    );
  }, [locations, data, records]);

  if (!data || !locations) {
    return (
      <section className="s1-content s1-xr s1-xr--doconly">
        <button className="s1-linklike s1-backlink" type="button" onClick={onBack}>
          ‹ Back to {backLabel}
        </button>
        <p role={loadError ? "alert" : "status"}>{loadError ?? "Opening the document."}</p>
      </section>
    );
  }

  const selected = sel ? byKey.get(locKey(sel.fieldId, sel.entry)) : undefined;
  const selectedMarkIds = sel && selected?.located ? marks.filter((m) => m.id.startsWith(`${sel.fieldId}#${sel.entry ?? ""}#`)).map((m) => m.id) : [];
  const firstBox = selectedMarkIds.length ? marks.find((m) => m.id === selectedMarkIds[0])?.span ?? null : null;
  const page = selected?.page ?? citedPage;
  const pageNote = sel && !selected?.located ? (page ? NOT_LOCATED_ON_PAGE : NOT_LOCATED) : null;

  function select(fieldId: string, entry: number | null, cited?: number | null) {
    setSel({ fieldId, entry });
    setCitedPage(cited ?? byKey.get(locKey(fieldId, entry))?.page ?? null);
  }

  const aiOff = aiStatusWords(data.ai);
  const aiBlocker = aiOff;

  // The same grid as every other document's review (ExtractionReview): navigator, the document in the
  // middle, the values on the right (the stylesheet orders the panes; the document comes first in the markup).
  return (
    <section className="s1-content s1-xr">
      <div className="s1-xr-grid">
        <aside className="s1-xr-nav" aria-label="Navigator">
          <button className="s1-linklike s1-backlink s1-xr-back" type="button" onClick={onBack}>
            ‹ Back to {backLabel}
          </button>
        </aside>
        <aside className="s1-xr-source" aria-label="Source">
          <div className="s1-xr-src">
            <div className="s1-xr-src-head">
              <div className="s1-xr-src-fn">{fileName}</div>
              <div className="s1-muted">The uploaded document, each fact outlined where it was read.</div>
            </div>
            <div className="s1-xr-src-body">
              <div className="s1-xr-page s1-xr-realpage">
                {renderViewer({
                  page,
                  span: firstBox,
                  marks,
                  selectedMarkIds,
                  pageNote,
                  viewerKey: `${sel?.fieldId ?? ""}|${sel?.entry ?? ""}|${page ?? ""}`,
                  onPickMark: (mark) => {
                    const [fieldId, entry] = mark.id.split("#");
                    select(fieldId, entry === "" ? null : Number(entry));
                    window.requestAnimationFrame(() =>
                      document.querySelector<HTMLElement>(`[data-field-id="${CSS.escape(fieldId)}"]`)?.scrollIntoView?.({ block: "nearest" })
                    );
                  },
                })}
              </div>
            </div>
          </div>
        </aside>
        <div className="s1-xr-values" aria-label="Methodology facts">
          {notice ? (
            <p className="s1-mb-notice" role="alert">
              {notice}
            </p>
          ) : null}
          {groups.length === 0 ? (
            <div className="s1-mb-confirm">
              <p className="s1-sd__note">
                No methodology facts have been read from this document yet. Sustentra&apos;s AI reads the engagement&apos;s company-prepared documents (up to five) and suggests what they state, each with a quote. Nothing counts until you accept or edit it.
              </p>
              <span className="s1-mr-actions">
                <button type="button" className="s1-button s1-button--pri" disabled={busy || aiBlocker !== null} onClick={() => void readWithAi()}>
                  {busy ? "Reading…" : "Read with Sustentra's AI"}
                </button>
                {aiBlocker ? <span className="s1-mb-ai">{aiBlocker}</span> : null}
              </span>
            </div>
          ) : (
            groups.map(({ group, label, defs }) => (
              <section key={group} className="s1-mr-card">
                <div className="s1-mr-card__head">
                  <h3 className="s1-mr-card__title">{label}</h3>
                </div>
                <ul className="s1-mb-list">
                  {defs.map((def) => {
                    const first = (locations ?? []).find((l) => l.fieldId === def.fieldId);
                    return (
                      <FieldRow
                        key={def.fieldId}
                        engagementId={engagementId}
                        def={def}
                        record={records.get(def.fieldId)!}
                        busy={busy}
                        entitiesNamed={false}
                        onMarkFollowUp={() => undefined}
                        onAct={(run) => void act(run)}
                        onOpenDocument={(_id, source: SourceAt | undefined) => select(def.fieldId, source?.entry ?? first?.entry ?? null, source?.page)}
                        selected={sel?.fieldId === def.fieldId}
                        onSelect={() => {
                          if (sel?.fieldId !== def.fieldId) select(def.fieldId, first?.entry ?? null);
                        }}
                        quoteNote={(entry) => {
                          const place = byKey.get(locKey(def.fieldId, entry));
                          return place && !place.located ? (place.page ? `${NOT_LOCATED} on page ${place.page}` : NOT_LOCATED) : null;
                        }}
                      />
                    );
                  })}
                </ul>
              </section>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

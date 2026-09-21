"use client";

import { Fragment, useMemo, useRef, useState, type ReactNode } from "react";

import type { EngagementConfig } from "../types";
import type { ReviewSpan, ReviewValue, ScopePlacement, ValueReviewState } from "../types/review";
import type { AskDraft } from "../requests/requestsStore";
import { AddToRequestsModal, type AddToRequestsTarget } from "./AddToRequestsModal";

/**
 * Extraction Review (screen 3), built to the 09/16 revision. Three panes:
 * navigator (facility -> type, entity-level workbook sections, not-yet-known) ·
 * values as cards · source at the page with the selected value highlighted.
 *
 * Correct: per the revision, the button is rendered and the record shape is
 * wired (corrected values keep the machine original visible), but the inline
 * edit surface is deferred pending verifier feedback — see onCorrect.
 */

interface ExtractionReviewProps {
  engagement: EngagementConfig;
  values: ReviewValue[];
  /** Lifts review state (accept/correct/request) to app state so a verifier's
   *  judgment survives navigation. Same pattern as the requests/findings stores. */
  onValuesChange: (updater: (cur: ReviewValue[]) => ReviewValue[]) => void;
  initialDocumentId?: string | null;
  /** Facility->type (or entity/not-yet-known) node the clicked row maps to, so
   *  a row whose exact document has no extracted value still deep-links to the
   *  right node rather than the first one. */
  initialNodeKey?: string;
  onSaveAsk: (draft: AskDraft) => void;
  onBack: () => void;
  /** Render the real source page for a document (else a facsimile is drawn).
   *  `onPickBox` lets a clicked highlight on the page select its value card. */
  renderPage?: (
    documentId: string,
    span: ReviewSpan | null,
    onPickBox?: (box: { x: number; y: number; w: number; h: number }) => void
  ) => ReactNode | null;
}

const SCOPE_LABEL: Record<ScopePlacement, string> = {
  general: "General",
  scope1: "Scope 1",
  scope2_location: "Scope 2 · location-based",
  scope2_market: "Scope 2 · market-based",
  not_placed: "Not placed",
};

const REVIEW_CAP = 60; // stressor render cap; the count still shows the true total

export function ExtractionReview({ engagement, values, onValuesChange, initialDocumentId, initialNodeKey, onSaveAsk, onBack, renderPage }: ExtractionReviewProps) {
  // Review data lives in app state (via onValuesChange); selection below is
  // local, ephemeral UI. So accepts/corrections/requests survive navigation.
  const items = values;

  const initial = useMemo(
    () => resolveInitial(items, initialDocumentId, initialNodeKey),
    [items, initialDocumentId, initialNodeKey]
  );

  const [nodeKey, setNodeKey] = useState<string>(initial.nodeKey);
  const [selectedId, setSelectedId] = useState<string | null>(initial.valueId);
  const [filter, setFilter] = useState<ValueReviewState | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(initial.rootKey ? [initial.rootKey] : []));
  const [modalTarget, setModalTarget] = useState<AddToRequestsTarget | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | null>(null);

  function flash(message: string) {
    setToast(message);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2400);
  }

  const tree = useMemo(() => buildTree(items, engagement), [items, engagement]);
  const nodeValues = useMemo(() => valuesForNode(items, nodeKey), [items, nodeKey]);
  const filtered = filter ? nodeValues.filter((v) => v.reviewState === filter) : nodeValues;
  const selected = items.find((v) => v.id === selectedId) ?? null;

  const counts = useMemo(() => {
    const c = { to_review: 0, accepted: 0, corrected: 0, requested: 0 };
    nodeValues.forEach((v) => (c[v.reviewState] += 1));
    return c;
  }, [nodeValues]);

  const flatNodeOrder = useMemo(() => flattenSelectableNodes(tree), [tree]);

  function selectNode(key: string) {
    setNodeKey(key);
    setFilter(null);
    const first = valuesForNode(items, key);
    const firstToReview = first.find((v) => v.reviewState === "to_review") ?? first[0];
    setSelectedId(firstToReview?.id ?? null);
  }

  function selectValue(v: ReviewValue) {
    setSelectedId(v.id);
  }

  /** A highlight on the document was clicked: select the value it belongs to. */
  function selectByBox(box: { x: number; y: number; w: number; h: number }) {
    const match = items.find(
      (v) => v.span && Math.abs(v.span.x - box.x) < 0.003 && Math.abs(v.span.y - box.y) < 0.003
    );
    if (!match) return;
    const nk = nodeKeyForValue(match);
    if (nk !== nodeKey) {
      setNodeKey(nk);
      setFilter(null);
      setExpanded((s) => new Set(s).add(rootKeyOf(match)));
    }
    setSelectedId(match.id);
  }

  function accept(v: ReviewValue) {
    const now = new Date().toISOString();
    onValuesChange((cur) =>
      cur.map((x) =>
        x.id === v.id
          ? {
              ...x,
              reviewState: "accepted",
              record: [
                ...x.record,
                {
                  kind: "human",
                  actor: "M. Osei",
                  at: now,
                  action: "accepted as read",
                  // Carry the S1->S2 handoff id: Accept is what mints the
                  // MethodologyValue keyed on this methodology field.
                  reason: v.methodologyFieldId ? `mints methodology value ${v.methodologyFieldId}` : undefined,
                },
              ],
            }
          : x
      )
    );
    flash("Accepted · number, unit, field, facility and period confirmed");
    advanceFrom(v);
  }

  function advanceFrom(v: ReviewValue) {
    // next to-review in the current node, else first to-review in the next node
    const here = valuesForNode(items, nodeKey).filter((x) => x.id !== v.id || x.reviewState !== "to_review");
    const next = here.find((x) => x.reviewState === "to_review");
    if (next) {
      setSelectedId(next.id);
      return;
    }
    const idx = flatNodeOrder.indexOf(nodeKey);
    for (let i = idx + 1; i < flatNodeOrder.length; i += 1) {
      const nk = flatNodeOrder[i];
      const first = valuesForNode(items, nk).find((x) => x.reviewState === "to_review");
      if (first) {
        setNodeKey(nk);
        setSelectedId(first.id);
        setExpanded((s) => new Set(s).add(rootKeyFromNode(nk)));
        return;
      }
    }
  }

  // Correct: per the revision, the control is present and the record shape is
  // wired (corrected values keep the machine original visible), but the inline
  // editor is deferred — the button renders disabled with a reason.
  // TODO(product): build the inline editor (number · unit · field · facility ·
  // period, with "not a value" last) once verifier feedback lands.

  function openAddToRequests(v: ReviewValue) {
    const facilityName = v.facilityId ? engagement.facilities.find((f) => f.facilityId === v.facilityId)?.name ?? null : null;
    const scope = SCOPE_LABEL[v.scope];
    const facLabel = facilityName ?? (v.entityLevel ? "entity-level" : "not yet known");
    setModalTarget({
      origin: "review_value",
      documentId: v.documentId,
      fieldKey: v.id,
      // The value WITH its document name (spec) — this shows on Evidence requests.
      itemLabel: `${v.whatItIs} · ${v.filename}`,
      facilityName,
      period: v.period,
      sourcePage: v.page,
      headerLine: `${v.filename} · page ${v.page} · ${v.whatItIs} · ${scope} · ${facLabel} · ${v.period}`,
      defaultType: v.requestPreselect ?? "clarify",
      // pre-fill order: document, value, scope, facility, period, then a colon
      prefill: `${v.filename} · ${v.value} ${v.unit} · ${scope} · ${facLabel} · ${v.period}: `,
    });
  }

  function submitAsk(draft: AskDraft) {
    onSaveAsk(draft);
    if (modalTarget?.fieldKey) {
      const now = new Date().toISOString();
      onValuesChange((cur) =>
        cur.map((x) =>
          x.id === modalTarget.fieldKey
            ? {
                ...x,
                reviewState: "requested",
                record: [...x.record, { kind: "human", actor: "M. Osei", at: now, action: "requested from client" }],
              }
            : x
        )
      );
    }
    setModalTarget(null);
    flash("Added to requests · not yet sent");
  }

  if (items.length === 0) {
    return (
      <section className="s1-content s1-xr">
        <button className="s1-linklike" type="button" onClick={onBack}>
          ‹ Back to evidence
        </button>
        <div className="s1-ws-empty">No values to review yet.</div>
      </section>
    );
  }

  return (
    <section className="s1-content s1-xr">
      <div className="s1-xr-grid">
        {/* Navigator */}
        <aside className="s1-xr-nav" aria-label="Navigator">
          <button className="s1-linklike s1-xr-back" type="button" onClick={onBack}>
            ‹ Back to evidence
          </button>
          {tree.map((root) => (
            <div key={root.key} className="s1-xr-navgroup">
              <button
                className={`s1-xr-node s1-xr-node--root${root.toReview === 0 ? " is-dim" : ""}${nodeKey === root.key ? " is-on" : ""}`}
                type="button"
                onClick={() => {
                  setExpanded((s) => {
                    const next = new Set(s);
                    if (next.has(root.key)) next.delete(root.key);
                    else next.add(root.key);
                    return next;
                  });
                  selectNode(root.key);
                }}
              >
                <span className="s1-xr-caret">{expanded.has(root.key) ? "▾" : "▸"}</span>
                <span className="s1-xr-node__label">{root.label}</span>
                <span className="s1-xr-node__count">{root.toReview === 0 ? "✓" : root.toReview}</span>
              </button>
              {expanded.has(root.key)
                ? root.children.map((child) => (
                    <button
                      key={child.key}
                      className={`s1-xr-node s1-xr-node--child${child.toReview === 0 ? " is-dim" : ""}${nodeKey === child.key ? " is-on" : ""}`}
                      type="button"
                      onClick={() => selectNode(child.key)}
                    >
                      <span className="s1-xr-node__label">{child.label}</span>
                      <span className="s1-xr-node__count">{child.toReview === 0 ? "✓" : child.toReview}</span>
                    </button>
                  ))
                : null}
            </div>
          ))}
        </aside>

        {/* Values */}
        <div className="s1-xr-values">
          <div className="s1-xr-vhead">
            <h2>{nodeHeaderLabel(nodeKey, engagement)}</h2>
            <div className="s1-xr-filters">
              {(["to_review", "accepted", "corrected", "requested"] as ValueReviewState[]).map((k) => (
                <button
                  key={k}
                  className={`s1-xr-filter${filter === k ? " is-on" : ""}`}
                  type="button"
                  onClick={() => setFilter((cur) => (cur === k ? null : k))}
                >
                  <span className="s1-xr-filter__n">{counts[k]}</span> {reviewStateLabel(k)}
                </button>
              ))}
            </div>
          </div>

          {filtered.length === 0 ? (
            <div className="s1-ws-empty">
              No values match {reviewStateLabel(filter ?? "to_review")}.
            </div>
          ) : (
            groupValues(filtered).map((group) => {
              const capped = group.values.slice(0, REVIEW_CAP);
              const hidden = group.values.length - capped.length;
              return (
                <div key={group.key} className="s1-xr-group">
                  <div className="s1-xr-doc">
                    <span className="s1-xr-doc__fn">{group.filename}</span>
                    <span className="s1-muted">{group.period}</span>
                    {group.values.length > REVIEW_CAP ? (
                      <span className="s1-muted"> · {group.values.length} values from one file</span>
                    ) : null}
                  </div>
                  {capped.map((v) => (
                    <ValueCard
                      key={v.id}
                      v={v}
                      selected={selectedId === v.id}
                      onSelect={() => selectValue(v)}
                      onAccept={() => accept(v)}
                      onAddToRequests={() => openAddToRequests(v)}
                    />
                  ))}
                  {hidden > 0 ? (
                    <div className="s1-xr-wall">
                      <strong>One card per value does not survive this file.</strong> Showing {capped.length} of{" "}
                      {group.values.length}; {hidden} more continue below, identical. Candidate treatment (product&rsquo;s call):
                      a table mode for high-cardinality sources.
                    </div>
                  ) : null}
                </div>
              );
            })
          )}
        </div>

        {/* Source */}
        <aside className="s1-xr-source" aria-label="Source">
          <SourcePane value={selected} renderPage={renderPage} onPickBox={selectByBox} />
        </aside>
      </div>

      {modalTarget ? (
        <AddToRequestsModal
          target={modalTarget}
          engagement={engagement}
          onCancel={() => setModalTarget(null)}
          onAdd={submitAsk}
        />
      ) : null}

      {toast ? <div className="s1-ws-toast">{toast}</div> : null}
    </section>
  );
}

/* =============================== value card =============================== */

function ValueCard({
  v,
  selected,
  onSelect,
  onAccept,
  onAddToRequests,
}: {
  v: ReviewValue;
  selected: boolean;
  onSelect: () => void;
  onAccept: () => void;
  onAddToRequests: () => void;
}) {
  const done = v.reviewState !== "to_review";
  return (
    <article
      className={`s1-xr-card${selected ? " is-sel" : ""} s1-xr-card--${v.reviewState}${v.withdrawn ? " s1-xr-card--withdrawn" : ""}`}
      onClick={onSelect}
      tabIndex={0}
      aria-current={selected}
      onKeyDown={(e) => {
        if (e.key === "Enter") onSelect();
      }}
    >
      <div className="s1-xr-gutter" aria-hidden>
        {v.reviewState === "accepted" ? "✓" : v.reviewState === "corrected" ? "✎" : v.reviewState === "requested" ? "◷" : "·"}
      </div>
      <div className="s1-xr-body">
        <div className="s1-xr-l1">
          <span>{v.documentType}</span>
          <span className="s1-xr-dot">·</span>
          <span className="s1-xr-what">{v.whatItIs}</span>
          <span className="s1-xr-dot">·</span>
          <span>{v.period}</span>
        </div>
        <div className="s1-xr-l2">
          <span className={`s1-xr-scope s1-xr-scope--${v.scope}`}>{SCOPE_LABEL[v.scope]}</span>
        </div>
        <div className="s1-xr-l3">
          <span className="s1-xr-val">{v.value}</span>
          {v.unit ? <span className="s1-xr-unit">{v.unit}</span> : null}
          {v.reviewState === "corrected" && v.originalValue ? (
            <span className="s1-xr-was">was {v.originalValue}</span>
          ) : null}
        </div>

        <div className="s1-xr-record">
          {v.record.map((r, i) => (
            <div key={i} className={`s1-xr-rec s1-xr-rec--${r.kind}`}>
              {r.kind === "machine" ? <span className="s1-xr-rec__mk" aria-hidden /> : <span className="s1-xr-rec__who">MO</span>}
              <span className="s1-xr-rec__act">{r.kind === "machine" ? "System read" : `${r.actor} · ${r.action}`}</span>
              {r.reason ? <span className="s1-muted"> · {r.reason}</span> : null}
              <span className="s1-mono s1-muted"> {formatTime(r.at)}</span>
            </div>
          ))}
        </div>

        <div className="s1-xr-actions" onClick={(e) => e.stopPropagation()}>
          {v.withdrawn ? (
            <span className="s1-reason">{v.withdrawnReason ?? "Document withdrawn; actions disabled."}</span>
          ) : done ? (
            <span className="s1-muted">{reviewStateLabel(v.reviewState)}</span>
          ) : (
            <>
              <button className="s1-button" type="button" onClick={onAccept}>
                Accept
              </button>
              <button className="s1-button" type="button" disabled title="Edit surface pending product confirmation">
                Correct
              </button>
              <button className="s1-button" type="button" onClick={onAddToRequests}>
                Add to requests
              </button>
            </>
          )}
        </div>
      </div>
    </article>
  );
}

/* =============================== source pane =============================== */

function SourcePane({
  value,
  renderPage,
  onPickBox,
}: {
  value: ReviewValue | null;
  renderPage?: (
    documentId: string,
    span: ReviewSpan | null,
    onPickBox?: (box: { x: number; y: number; w: number; h: number }) => void
  ) => ReactNode | null;
  onPickBox?: (box: { x: number; y: number; w: number; h: number }) => void;
}) {
  // Page state tracked here (hook must run every render); resets when the
  // selected value changes, guarded so it fires once per change.
  const [pageState, setPageState] = useState<{ id: string; page: number }>({
    id: value?.id ?? "",
    page: value?.page ?? 1,
  });
  if (value && pageState.id !== value.id) {
    setPageState({ id: value.id, page: value.page });
  }
  if (!value) {
    return (
      <div className="s1-xr-src-empty">
        <p className="s1-muted">Select a value to open its source.</p>
      </div>
    );
  }
  const page = pageState.id === value.id ? pageState.page : value.page;
  const setPage = (nextPage: number) => setPageState({ id: value.id, page: nextPage });
  const realPage = renderPage ? renderPage(value.documentId, value.span ?? null, onPickBox) : null;
  return (
    <div className="s1-xr-src">
      <div className="s1-xr-src-head">
        <div className="s1-xr-src-fn">{value.filename}</div>
        <div className="s1-muted">
          {value.span ? "Opened at the page, value highlighted." : "Highlight unavailable for this value."}
        </div>
        {value.sourceKind !== "text" ? (
          <div className="s1-xr-pager">
            <button className="s1-button s1-button--compact" type="button" onClick={() => setPage(Math.max(1, page - 1))} aria-label="Previous page">
              ‹
            </button>
            <span className="s1-mono s1-muted">page {page} of {value.pageCount}</span>
            <button
              className="s1-button s1-button--compact"
              type="button"
              onClick={() => setPage(Math.min(value.pageCount, page + 1))}
              aria-label="Next page"
            >
              ›
            </button>
          </div>
        ) : null}
      </div>
      <div className="s1-xr-src-body">
        {realPage ? (
          <div className="s1-xr-page s1-xr-realpage">{realPage}</div>
        ) : value.sourceKind === "spreadsheet" ? (
          <SheetView value={value} />
        ) : value.sourceKind === "text" ? (
          <div className="s1-xr-passage">{value.snippet}</div>
        ) : value.span && value.span.page === page ? (
          <PageView value={value} />
        ) : value.span ? (
          <div className="s1-xr-page">
            <div className="s1-muted s1-xr-page__note">The highlight is on page {value.span.page}.</div>
          </div>
        ) : (
          <div className="s1-xr-fallback">
            <strong>The extractor gave no span.</strong> The source is open at the page; the highlight could not be placed.
            <div className="s1-xr-snip">{value.snippet ?? value.value}</div>
          </div>
        )}
      </div>
    </div>
  );
}

/** A synthetic document page with the highlight overlaid at the fixture span. */
function PageView({ value }: { value: ReviewValue }) {
  const span = value.span!;
  return (
    <div className="s1-xr-page">
      <div className="s1-xr-paper">
        <div className="s1-xr-paper__co">{value.documentType}</div>
        <div className="s1-xr-paper__meta">{value.filename}</div>
        <div className="s1-xr-paper__row"><span>Service</span><span>{value.period}</span></div>
        <div className="s1-xr-paper__row"><span>{value.whatItIs}</span><span>{value.value} {value.unit}</span></div>
        <div className="s1-xr-paper__row"><span>Prepared for</span><span>Cascade Provisions</span></div>
        <div
          className="s1-xr-highlight"
          style={{ left: `${span.x * 100}%`, top: `${span.y * 100}%`, width: `${span.w * 100}%`, height: `${span.h * 100}%` }}
          aria-hidden
        />
      </div>
    </div>
  );
}

function SheetView({ value }: { value: ReviewValue }) {
  const cols = ["A", "B", "C", "D", "E"];
  const rows = [1, 2, 3, 4, 5];
  const targetCol = value.cell?.[0];
  const targetRow = value.cell ? Number(value.cell.slice(1)) : null;
  return (
    <div className="s1-xr-sheet">
      <div className="s1-muted s1-xr-sheet__head">
        Sheet: {value.sheet} · cell {value.cell} outlined
      </div>
      <table className="s1-xr-sheet__table">
        <tbody>
          {rows.map((r) => (
            <tr key={r}>
              {cols.map((c) => {
                const isTarget = c === targetCol && (targetRow === r || (targetRow && targetRow > 5 && r === 5));
                return (
                  <td key={c} className={isTarget ? "is-target" : ""}>
                    {isTarget ? `${value.value} ${value.unit}` : ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {value.cell && Number(value.cell.slice(1)) > 5 ? (
        <div className="s1-muted s1-xr-sheet__note">Row {value.cell.slice(1)} shown at the last row for layout.</div>
      ) : null}
    </div>
  );
}

/* =============================== tree helpers =============================== */

interface TreeNode {
  key: string;
  label: string;
  toReview: number;
  children: Array<{ key: string; label: string; toReview: number }>;
}

function buildTree(items: ReviewValue[], engagement: EngagementConfig): TreeNode[] {
  const nodes: TreeNode[] = [];
  const toReview = (vs: ReviewValue[]) => vs.filter((v) => v.reviewState === "to_review").length;

  // Entity-level first (spec: node at the top).
  const entity = items.filter((v) => v.entityLevel);
  if (entity.length) {
    const children: TreeNode["children"] = [];
    const sections: Array<["general" | "scope1" | "scope2", string]> = [
      ["general", "General"],
      ["scope1", "Scope 1"],
      ["scope2", "Scope 2"],
    ];
    sections.forEach(([s, label]) => {
      const vs = entity.filter((v) => v.section === s);
      if (vs.length) children.push({ key: `E|S:${s}`, label, toReview: toReview(vs) });
    });
    const typed = entity.filter((v) => !v.section);
    distinct(typed.map((v) => v.documentType)).forEach((t) => {
      const vs = typed.filter((v) => v.documentType === t);
      children.push({ key: `E|T:${t}`, label: t, toReview: toReview(vs) });
    });
    nodes.push({ key: "E", label: "Entity-level", toReview: toReview(entity), children });
  }

  // Facilities in Setup order.
  engagement.facilities.forEach((f) => {
    const vs = items.filter((v) => v.facilityId === f.facilityId && !v.entityLevel && !v.notYetKnown);
    if (!vs.length) return;
    const children = distinct(vs.map((v) => v.documentType)).map((t) => {
      const tv = vs.filter((v) => v.documentType === t);
      return { key: `F:${f.facilityId}|T:${t}`, label: t, toReview: toReview(tv) };
    });
    nodes.push({ key: `F:${f.facilityId}`, label: f.name, toReview: toReview(vs), children });
  });

  // Not yet known last.
  const nyk = items.filter((v) => v.notYetKnown);
  if (nyk.length) {
    const children = distinct(nyk.map((v) => v.documentType)).map((t) => {
      const tv = nyk.filter((v) => v.documentType === t);
      return { key: `N|T:${t}`, label: t, toReview: toReview(tv) };
    });
    nodes.push({ key: "N", label: "Not yet known", toReview: toReview(nyk), children });
  }

  return nodes;
}

function flattenSelectableNodes(tree: TreeNode[]): string[] {
  const out: string[] = [];
  tree.forEach((root) => {
    out.push(root.key);
    root.children.forEach((c) => out.push(c.key));
  });
  return out;
}

function valuesForNode(items: ReviewValue[], key: string): ReviewValue[] {
  if (!key) return [];
  if (key === "E") return items.filter((v) => v.entityLevel);
  if (key === "N") return items.filter((v) => v.notYetKnown);
  if (key.startsWith("E|S:")) {
    const s = key.slice(4);
    return items.filter((v) => v.entityLevel && v.section === s);
  }
  if (key.startsWith("E|T:")) {
    const t = key.slice(4);
    return items.filter((v) => v.entityLevel && !v.section && v.documentType === t);
  }
  if (key.startsWith("N|T:")) {
    const t = key.slice(4);
    return items.filter((v) => v.notYetKnown && v.documentType === t);
  }
  if (key.includes("|T:")) {
    const [fac, typePart] = key.split("|T:");
    const fid = fac.slice(2);
    return items.filter((v) => v.facilityId === fid && !v.entityLevel && !v.notYetKnown && v.documentType === typePart);
  }
  if (key.startsWith("F:")) {
    const fid = key.slice(2);
    return items.filter((v) => v.facilityId === fid && !v.entityLevel && !v.notYetKnown);
  }
  return [];
}

function nodeKeyForValue(v: ReviewValue): string {
  if (v.entityLevel) return v.section ? `E|S:${v.section}` : `E|T:${v.documentType}`;
  if (v.notYetKnown) return `N|T:${v.documentType}`;
  return `F:${v.facilityId}|T:${v.documentType}`;
}

function rootKeyOf(v: ReviewValue): string {
  if (v.entityLevel) return "E";
  if (v.notYetKnown) return "N";
  return `F:${v.facilityId}`;
}

/**
 * Resolve the initial selection. Prefer the exact document's value; otherwise
 * the node the clicked row maps to; otherwise that node's root; otherwise the
 * first value. So every Workspace row deep-links to the right place.
 */
function resolveInitial(
  items: ReviewValue[],
  docId: string | null | undefined,
  nodeKeyHint: string | undefined
): { nodeKey: string; valueId: string | null; rootKey: string | null } {
  if (!items.length) return { nodeKey: "", valueId: null, rootKey: null };
  const byDoc = docId ? items.find((v) => v.documentId === docId) : undefined;
  if (byDoc) return { nodeKey: nodeKeyForValue(byDoc), valueId: byDoc.id, rootKey: rootKeyOf(byDoc) };
  if (nodeKeyHint) {
    const atHint = valuesForNode(items, nodeKeyHint);
    if (atHint.length) {
      const f = atHint.find((v) => v.reviewState === "to_review") ?? atHint[0];
      return { nodeKey: nodeKeyHint, valueId: f.id, rootKey: rootKeyFromNode(nodeKeyHint) };
    }
    const root = rootKeyFromNode(nodeKeyHint);
    const atRoot = valuesForNode(items, root);
    if (atRoot.length) {
      const f = atRoot.find((v) => v.reviewState === "to_review") ?? atRoot[0];
      return { nodeKey: root, valueId: f.id, rootKey: root };
    }
  }
  const first = items[0];
  return { nodeKey: nodeKeyForValue(first), valueId: first.id, rootKey: rootKeyOf(first) };
}

function rootKeyFromNode(key: string): string {
  if (key.startsWith("E")) return "E";
  if (key.startsWith("N")) return "N";
  return key.split("|")[0];
}

function nodeHeaderLabel(key: string, engagement: EngagementConfig): string {
  if (key === "E" || key.startsWith("E|")) return "Entity-level";
  if (key === "N" || key.startsWith("N|")) return "Not yet known";
  const fid = key.slice(2).split("|")[0];
  return engagement.facilities.find((f) => f.facilityId === fid)?.name ?? "Facility";
}

function groupValues(values: ReviewValue[]): Array<{ key: string; filename: string; period: string; values: ReviewValue[] }> {
  const map = new Map<string, ReviewValue[]>();
  values.forEach((v) => {
    const key = `${v.filename}__${v.period}`;
    map.set(key, [...(map.get(key) ?? []), v]);
  });
  return Array.from(map.entries()).map(([key, vs]) => ({ key, filename: vs[0].filename, period: vs[0].period, values: vs }));
}

function distinct(xs: string[]): string[] {
  return Array.from(new Set(xs));
}

function reviewStateLabel(s: ValueReviewState): string {
  return s === "to_review" ? "To review" : s === "accepted" ? "Accepted" : s === "corrected" ? "Corrected" : "Requested";
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

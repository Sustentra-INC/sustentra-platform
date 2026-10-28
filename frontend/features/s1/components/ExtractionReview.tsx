"use client";

import { Highlighter, Plus } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { withRequestsFromAsks } from "../adapters/reviewValueAdapter";
import type { EngagementConfig } from "../types";
import type { PageMark, ReviewSpan, ReviewValue, ScopePlacement, ValueRecordEntry, ValueReviewState } from "../types/review";
import type { Ask } from "../types/requests";
import { andThen, type MaybePromise } from "../requests/maybePromise";
import type { AskDraft } from "../requests/requestsStore";
import { AddToRequestsModal, type AddToRequestsTarget } from "./AddToRequestsModal";
import { readablePeriod } from "../utils/formatPeriod";
import type { HighlightEntry } from "./demo/DemoDocument";

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
  /** The opened document's file name, said when no value was read from it. */
  initialDocumentName?: string;
  /** Open with this value selected (a link from the assistant). */
  initialValueId?: string;
  /** Facility->type (or entity/not-yet-known) node the clicked row maps to, so
   *  a row whose exact document has no extracted value still deep-links to the
   *  right node rather than the first one. */
  initialNodeKey?: string;
  /** Saves an ask; returns it so the value's record can point at it. It may answer after the
   *  server has: the value turns "requested" only once the save has gone through. */
  onSaveAsk: (draft: AskDraft) => MaybePromise<Ask | void>;
  /** The server records who raised a request: the Add to requests window does not ask, and the
   *  value's record names the person the server named. */
  serverRecordsActor?: boolean;
  /** The engagement's asks: a card added to requests says whether its request was sent. */
  asks?: Ask[];
  onBack: () => void;
  /** Render the real source page for a document (else a facsimile is drawn).
   *  `onPickBox` lets a clicked highlight on the page select its value card (by its id
   *  when the page knows it); `marks` are every value of the document that has a position.
   *  `pick` serves files drawn as content (workbook, CSV, Word): the selected value, and a
   *  click on a spot holding several values (`ids`) selects the next of them. */
  renderPage?: (
    documentId: string,
    span: ReviewSpan | null,
    onPickBox?: (box: { x: number; y: number; w: number; h: number }, id?: string) => void,
    marks?: PageMark[],
    pick?: SourcePick
  ) => ReactNode | null;
  /** Who the record names for a human action. */
  reviewerName?: string;
  /** Records an accept on the backend; on failure the card goes back to "to review". */
  onPersistAccept?: (value: ReviewValue) => Promise<void>;
  /** Records a correction on the backend; on failure the card goes back to how it was. */
  onPersistCorrect?: (value: ReviewValue, next: { value: string; unit: string }) => Promise<void>;
  /** Lets the reviewer key a value the reading missed (kept in the session; not yet saved to the backend). */
  allowAddValue?: boolean;
  /** A value was added or filled in by the reviewer: the rest of the workspace follows. */
  onValueAdded?: (value: ReviewValue, filled: boolean) => void;
  /** The document is drawn whole by the app (the demo's documents): with allowAddValue, the
   *  key above the cards offers the switch to highlight a figure on it. The key itself shows
   *  for any document the source pane draws (renderPage), in both data modes. */
  drawnWhole?: (documentId: string) => boolean;
}

const SCOPE_LABEL: Record<ScopePlacement, string> = {
  general: "General",
  scope1: "Scope 1",
  scope2_location: "Scope 2 · location-based",
  scope2_market: "Scope 2 · market-based",
  scope2_both: "Scope 2 · location- and market-based",
  not_placed: "Not placed",
};

const REVIEW_CAP = 60; // stressor render cap; the count still shows the true total
const NO_ASKS: Ask[] = [];

export function ExtractionReview({
  engagement,
  values,
  onValuesChange,
  initialDocumentId,
  initialDocumentName,
  initialValueId,
  initialNodeKey,
  onSaveAsk,
  serverRecordsActor = false,
  asks = NO_ASKS,
  onBack,
  renderPage,
  reviewerName = "M. Osei",
  onPersistAccept,
  onPersistCorrect,
  allowAddValue = false,
  onValueAdded,
  drawnWhole,
}: ExtractionReviewProps) {
  // Review data lives in app state (via onValuesChange); selection below is
  // local, ephemeral UI. So accepts/corrections/requests survive navigation.
  // A card's latest request decides whether it is requested (resolved or withdrawn: back to review).
  const items = useMemo(() => withRequestsFromAsks(values, asks), [values, asks]);

  const initial = useMemo(
    () => resolveInitial(items, initialDocumentId, initialNodeKey, initialValueId),
    [items, initialDocumentId, initialNodeKey, initialValueId]
  );

  // A document opened with no values: say so, rather than open another document's value.
  const [unreadDocument] = useState<string | null>(() =>
    initialDocumentId && !initialValueId && !items.some((v) => v.documentId === initialDocumentId) ? (initialDocumentName ?? "this document") : null
  );
  const [nodeKey, setNodeKey] = useState<string>(initial.nodeKey);
  const [selectedId, setSelectedId] = useState<string | null>(unreadDocument ? null : initial.valueId);
  const [filter, setFilter] = useState<ValueReviewState | null>(null);
  // A long document: show the values of one page at a time.
  const [pageFilter, setPageFilter] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  // Highlight mode, for one document: it ends when another document is selected.
  const [highlightDoc, setHighlightDoc] = useState<string | null>(null);
  // A pick on the document asks the values pane to bring the picked card into view.
  const [scrollTo, setScrollTo] = useState<{ id: string; tick: number } | null>(null);
  const valuesPane = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(initial.rootKey ? [initial.rootKey] : []));
  const [modalTarget, setModalTarget] = useState<AddToRequestsTarget | null>(null);
  // The values a request is for: every data point of the reading.
  const [requestIds, setRequestIds] = useState<string[]>([]);
  // A toast shows for 2.4 seconds; a new one starts the time again. Kept in state, not a
  // timer ref, so the page drawn during render (renderPage) can be handed callbacks that flash.
  const [toast, setToast] = useState<{ message: string } | null>(null);
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2400);
    return () => window.clearTimeout(timer);
  }, [toast]);

  function flash(message: string) {
    setToast({ message });
  }

  const tree = useMemo(() => buildTree(items, engagement), [items, engagement]);
  const askById = useMemo(() => new Map(asks.map((a) => [a.id, a])), [asks]);
  const nodeValues = useMemo(() => valuesForNode(items, nodeKey), [items, nodeKey]);
  const filtered = nodeValues.filter(
    (v) => (!filter || v.reviewState === filter) && (pageFilter === null || v.page === pageFilter)
  );
  const selected = items.find((v) => v.id === selectedId) ?? null;
  const canHighlight = Boolean(selected && drawnWhole?.(selected.documentId) && allowAddValue && !selected.withdrawn);
  const highlighting = canHighlight && highlightDoc === selected?.documentId;

  // Counted by card: values that share one reading are one card.
  const counts = useMemo(() => {
    const c = { to_review: 0, accepted: 0, corrected: 0, requested: 0 };
    readings(nodeValues).forEach((vs) => (c[vs[0].reviewState] += 1));
    return c;
  }, [nodeValues]);

  const flatNodeOrder = useMemo(() => flattenSelectableNodes(tree), [tree]);

  function selectNode(key: string) {
    setNodeKey(key);
    setFilter(null);
    setPageFilter(null);
    const first = valuesForNode(items, key);
    const firstToReview = first.find((v) => v.reviewState === "to_review") ?? first[0];
    setSelectedId(firstToReview?.id ?? null);
  }

  function selectValue(v: ReviewValue) {
    setSelectedId(v.id);
  }

  /** A highlight on the document was clicked: select the value it belongs to. Several values
   *  can share one line ("Total kWh Used: 700,000 kWh" holds the amount and its unit), so a
   *  second click on the same box moves to the next of them. */
  function selectByBox(box: { x: number; y: number; w: number; h: number }, id?: string) {
    const sameBox = items.filter(
      (v) => v.span && Math.abs(v.span.x - box.x) < 0.003 && Math.abs(v.span.y - box.y) < 0.003
    );
    const byId = id ? items.find((v) => v.id === id) : undefined;
    const here = sameBox.findIndex((v) => v.id === selectedId);
    const match = here >= 0 && sameBox.length > 1 ? sameBox[(here + 1) % sameBox.length] : byId ?? sameBox[0];
    if (match) focusValue(match);
  }

  /** A spot in a workbook, CSV or Word file was clicked: `ids` are the values read there.
   *  The first is selected, or the next one when one of them already is. */
  function selectAmong(ids: string[]) {
    const here = selectedId ? ids.indexOf(selectedId) : -1;
    const nextId = here >= 0 ? ids[(here + 1) % ids.length] : ids[0];
    const match = items.find((v) => v.id === nextId);
    if (match) focusValue(match);
  }

  function focusValue(match: ReviewValue) {
    const nk = nodeKeyForValue(match);
    if (nk !== nodeKey) {
      setNodeKey(nk);
      setFilter(null);
      setExpanded((s) => new Set(s).add(rootKeyOf(match)));
    }
    if (pageFilter !== null && match.page !== pageFilter) setPageFilter(null);
    setSelectedId(match.id);
    setScrollTo((cur) => ({ id: match.id, tick: (cur?.tick ?? 0) + 1 }));
  }

  // Scroll the picked card to the middle of the values pane, and flash it.
  useEffect(() => {
    if (!scrollTo) return;
    const frame = window.requestAnimationFrame(() => {
      const pane = valuesPane.current;
      const card = pane?.querySelector<HTMLElement>(`[data-value-id="${CSS.escape(scrollTo.id)}"]`);
      if (!pane || !card) return;
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const box = card.getBoundingClientRect();
      const view = pane.getBoundingClientRect();
      pane.scrollTo({ top: pane.scrollTop + (box.top - view.top) - view.height / 2 + box.height / 2, behavior: reduce ? "auto" : "smooth" });
      card.classList.remove("is-flash");
      void card.offsetWidth; // restart the flash
      card.classList.add("is-flash");
    });
    return () => window.cancelAnimationFrame(frame);
  }, [scrollTo]);

  /** Accept one reading: every data point it feeds. */
  function accept(vs: ReviewValue[]) {
    const now = new Date().toISOString();
    const ids = new Set(vs.map((v) => v.id));
    onValuesChange((cur) =>
      cur.map((x) =>
        ids.has(x.id)
          ? {
              ...x,
              reviewState: "accepted",
              record: [
                ...x.record,
                {
                  kind: "human",
                  actor: reviewerName,
                  at: now,
                  action: "accepted as read",
                  // Carry the S1->S2 handoff id: Accept is what mints the
                  // MethodologyValue keyed on this methodology field.
                  reason: x.methodologyFieldId ? `mints methodology value ${x.methodologyFieldId}` : undefined,
                },
              ],
            }
          : x
      )
    );
    flash("Accepted · number, unit, field, facility and period confirmed");
    advanceFrom(ids);
    for (const v of vs) {
      onPersistAccept?.(v).catch((error: unknown) => {
        onValuesChange((cur) => cur.map((x) => (x.id === v.id ? v : x)));
        flash(`Not saved, back to review. ${error instanceof Error ? error.message : ""}`.trim());
      });
    }
  }

  /** Correct one reading: every data point it feeds. */
  function correct(vs: ReviewValue[], next: { value: string; unit: string }) {
    const v = vs[0];
    const now = new Date().toISOString();
    const was = `${v.value}${v.unit ? ` ${v.unit}` : ""}`;
    const ids = new Set(vs.map((x) => x.id));
    onValuesChange((cur) =>
      cur.map((x) =>
        ids.has(x.id)
          ? {
              ...x,
              reviewState: "corrected",
              // The machine's original stays visible beside the change.
              originalValue: x.originalValue ?? x.value,
              value: next.value,
              unit: next.unit,
              asPrinted: undefined,
              record: [
                ...x.record,
                {
                  kind: "human",
                  actor: reviewerName,
                  at: now,
                  action: v.value ? `corrected from ${was}` : "entered a value the extractor did not find",
                },
              ],
            }
          : x
      )
    );
    flash(`${v.value ? "Corrected to" : "Entered"} ${next.value}${next.unit ? ` ${next.unit}` : ""}`);
    if (v.reviewState === "to_review") advanceFrom(ids);
    for (const one of vs) {
      onPersistCorrect?.(one, next).catch((error: unknown) => {
        onValuesChange((cur) => cur.map((x) => (x.id === one.id ? one : x)));
        flash(`Correction not saved, back as it was. ${error instanceof Error ? error.message : ""}`.trim());
      });
    }
  }

  /** Accept every value of one document still to review, saving up to six at a time. */
  function acceptAll(documentId: string) {
    // Values not found on the document need the reviewer to enter them; they are never "accepted".
    const pending = items.filter(
      (x) => x.documentId === documentId && x.reviewState === "to_review" && !x.withdrawn && !x.missing
    );
    if (pending.length === 0) return;
    const now = new Date().toISOString();
    const ids = new Set(pending.map((x) => x.id));
    onValuesChange((cur) =>
      cur.map((x) =>
        ids.has(x.id)
          ? {
              ...x,
              reviewState: "accepted",
              record: [...x.record, { kind: "human", actor: reviewerName, at: now, action: "accepted as read (accept all)" }],
            }
          : x
      )
    );
    flash(`Accepted ${pending.length} value${pending.length === 1 ? "" : "s"} from this document`);
    if (!onPersistAccept) return;
    const failed: ReviewValue[] = [];
    const queue = [...pending];
    const worker = async () => {
      for (let next = queue.shift(); next; next = queue.shift()) {
        try {
          await onPersistAccept(next);
        } catch {
          failed.push(next);
        }
      }
    };
    void Promise.all(Array.from({ length: Math.min(6, queue.length) }, worker)).then(() => {
      if (failed.length === 0) return;
      const back = new Map(failed.map((x) => [x.id, x]));
      onValuesChange((cur) => cur.map((x) => back.get(x.id) ?? x));
      flash(`${failed.length} of ${pending.length} were not saved and are back to review.`);
    });
  }

  function advanceFrom(done: Set<string>) {
    // next to-review in the current node, else first to-review in the next node
    const here = valuesForNode(items, nodeKey).filter((x) => !done.has(x.id));
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

  function openAddToRequests(vs: ReviewValue[]) {
    const v = vs[0];
    const facilityName = v.facilityId ? engagement.facilities.find((f) => f.facilityId === v.facilityId)?.name ?? null : null;
    const scope = scopeLabels(vs).join(" + ");
    setRequestIds(vs.map((x) => x.id));
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
      headerLine: `${v.filename} · page ${v.page} · ${v.whatItIs} · ${scope} · ${facLabel} · ${readablePeriod(v.period)}`,
      defaultType: v.requestPreselect ?? "clarify",
      // pre-fill order: document, value, scope, facility, period, then a colon
      // The words go to the client: the value as the bill prints it, the period as a person reads it.
      // The request's own period (above) is saved as data.
      prefill: `${v.filename} · ${shown(v).value} ${shown(v).unit} · ${scope} · ${facLabel} · ${readablePeriod(v.period)}: `,
    });
  }

  /** A value the reading missed, keyed by the reviewer: reviewed on entry, with no machine
   *  reading behind it, and recorded as added by hand. Highlighted on the page, it keeps
   *  where (``docAnchor``); named like a value the reading could not find, it fills that in. */
  function addValue(
    base: ReviewValue,
    entry: { whatItIs: string; value: string; unit: string; page: number; scope?: ReviewValue["scope"]; docAnchor?: string }
  ) {
    const now = new Date().toISOString();
    const where = entry.docAnchor ? `highlighted on page ${entry.page}` : `keyed from page ${entry.page}`;
    const gap = items.find(
      (x) => x.documentId === base.documentId && (x.missing || x.value === "not found") && x.whatItIs.toLowerCase() === entry.whatItIs.toLowerCase()
    );
    let result: ReviewValue;
    if (gap) {
      result = {
        ...gap,
        value: entry.value,
        unit: entry.unit,
        page: entry.page,
        missing: false,
        docAnchor: entry.docAnchor,
        asPrinted: undefined,
        reviewState: "corrected",
        originalValue: "not found",
        record: [...gap.record, { kind: "human", actor: reviewerName, at: now, action: "filled in a value the reading missed", reason: where }],
      };
      onValuesChange((cur) => cur.map((x) => (x.id === gap.id ? result : x)));
    } else {
      result = {
        ...base,
        id: `keyed-${base.documentId}-${now}`,
        whatItIs: entry.whatItIs,
        value: entry.value,
        unit: entry.unit,
        page: entry.page,
        scope: entry.scope ?? base.scope,
        span: null,
        anchor: null,
        snippet: null,
        rawText: null,
        missing: false,
        docAnchor: entry.docAnchor,
        methodologyFieldId: undefined,
        reviewToken: undefined,
        asPrinted: undefined,
        reviewState: "corrected",
        originalValue: null,
        record: [{ kind: "human", actor: reviewerName, at: now, action: "added a value the reading missed", reason: where }],
      };
      onValuesChange((cur) => {
        const at = cur.findIndex((x) => x.id === base.id);
        return at < 0 ? [...cur, result] : [...cur.slice(0, at + 1), result, ...cur.slice(at + 1)];
      });
    }
    setAdding(false);
    setSelectedId(result.id);
    setScrollTo((cur) => ({ id: result.id, tick: (cur?.tick ?? 0) + 1 }));
    onValueAdded?.(result, Boolean(gap));
    flash(
      entry.docAnchor
        ? `${gap ? "Filled in" : "Added"}: ${entry.whatItIs}. Kept as a correction to the reading.`
        : `Added: ${entry.whatItIs}`
    );
  }

  function submitAsk(draft: AskDraft) {
    return andThen(onSaveAsk(draft), (ask) => {
      if (modalTarget?.fieldKey) {
        const now = new Date().toISOString();
        const ids = new Set(requestIds.length ? requestIds : [modalTarget.fieldKey]);
        // Nothing is sent yet: the record says the value was added to requests, and points at
        // the ask so the card can say "requested from client" once the request goes out. When the
        // server saved the ask, the record names the person and the time it recorded.
        const recorded = serverRecordsActor && ask ? { actor: ask.raisedByName, at: ask.raisedAt } : { actor: reviewerName, at: now };
        const entry: ValueRecordEntry = { kind: "human", ...recorded, action: "added to requests", ...(ask ? { askId: ask.id } : {}) };
        onValuesChange((cur) =>
          cur.map((x) =>
            ids.has(x.id)
              ? {
                  ...x,
                  reviewState: "requested",
                  record: [...x.record, entry],
                }
              : x
          )
        );
      }
      setModalTarget(null);
      flash("Added to requests · not yet sent");
    });
  }

  // The cards as listed, so arrow keys can move through them.
  const groups = groupValues(filtered).map((group) => {
    const cards = readings(group.values);
    const capped = cards.slice(0, REVIEW_CAP);
    // A value picked on the document beyond the cap still gets its card.
    const picked = cards.find((vs) => vs.some((x) => x.id === selectedId));
    if (picked && !capped.includes(picked)) capped.push(picked);
    return { ...group, cards, capped, hidden: Math.max(cards.length - capped.length, 0) };
  });
  const listed = groups.flatMap((g) => g.capped);

  // The selected value's document, drawn with its values marked (the demo's drawing, or the
  // uploaded file's pages or content). Whenever it is drawn, the key above the cards says what
  // its marks mean and how many values were read.
  const realPage =
    selected && renderPage
      ? renderPage(selected.documentId, selected.span ?? null, selectByBox, pageMarks(items, selected.documentId), {
          selectedId: selected.id,
          onPickAmong: selectAmong,
          onAddValue: allowAddValue && !selected.withdrawn ? (entry) => addValue(selected, entry) : undefined,
          highlighting,
          onHighlightingChange: (on) => setHighlightDoc(on ? selected.documentId : null),
        })
      : null;
  const keyed = Boolean(selected && realPage);

  /** ↑ and ↓ move through the cards; the document follows. */
  function onListKey(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    if ((e.target as HTMLElement).closest("input, textarea, select")) return;
    e.preventDefault();
    const at = listed.findIndex((vs) => vs.some((x) => x.id === selectedId));
    const next = listed[Math.max(0, Math.min(listed.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)))];
    if (!next) return;
    setSelectedId(next[0].id);
    window.requestAnimationFrame(() => {
      const card = valuesPane.current?.querySelector<HTMLElement>(`[data-value-id="${CSS.escape(next[0].id)}"]`);
      card?.scrollIntoView?.({ block: "nearest" });
      card?.focus({ preventScroll: true });
    });
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
        <div className="s1-xr-values" ref={valuesPane} onKeyDown={onListKey}>
          <div className="s1-xr-vhead">
            <div className="s1-xr-vhead__top">
              <h2>{nodeHeaderLabel(nodeKey, engagement)}</h2>
              {allowAddValue && (selected ?? nodeValues[0]) ? (
                <button className="s1-xr-addvalue" type="button" aria-expanded={adding} onClick={() => setAdding((v) => !v)}>
                  <Plus aria-hidden /> Add a value
                </button>
              ) : null}
            </div>
            <div className="s1-xr-filters" role="group" aria-label="Show cards by review state">
              {(["to_review", "accepted", "corrected", "requested"] as ValueReviewState[]).map((k) => (
                <button
                  key={k}
                  className={`s1-xr-filter s1-xr-filter--${k}${filter === k ? " is-on" : ""}`}
                  type="button"
                  aria-pressed={filter === k}
                  onClick={() => setFilter((cur) => (cur === k ? null : k))}
                >
                  <span className="s1-xr-filter__n">{counts[k]}</span>
                  <span className="s1-xr-filter__label">{filterLabel(k)}</span>
                </button>
              ))}
            </div>
            {selected && keyed ? (
              <DocumentKey
                values={items.filter((x) => x.documentId === selected.documentId && !x.withdrawn)}
                highlight={
                  canHighlight
                    ? { on: highlighting, toggle: () => setHighlightDoc(highlighting ? null : selected.documentId) }
                    : undefined
                }
              />
            ) : null}
          </div>

          {unreadDocument && !selectedId ? (
            <p className="s1-xr-unread" role="status">
              No values were read from <strong>{unreadDocument}</strong>. The cards below are the other documents here.
            </p>
          ) : null}

          {adding && (selected ?? nodeValues[0]) ? (
            <AddValueForm
              base={(selected ?? nodeValues[0]) as ReviewValue}
              suggestions={[...new Set(items.filter((x) => x.documentType === (selected ?? nodeValues[0])?.documentType).map((x) => x.whatItIs))]}
              onCancel={() => setAdding(false)}
              onAdd={(entry) => addValue((selected ?? nodeValues[0]) as ReviewValue, entry)}
            />
          ) : null}

          {filtered.length === 0 ? (
            <div className="s1-ws-empty">
              No values match {pageFilter !== null ? `page ${pageFilter}` : filterLabel(filter ?? "to_review")}.
            </div>
          ) : (
            groups.map(({ cards, capped, hidden, ...group }) => {
              return (
                <div key={group.key} className="s1-xr-group">
                  <div className="s1-xr-doc">
                    <span className="s1-xr-doc__fn">{group.filename}</span>
                    <span className="s1-muted">{readablePeriod(group.period)}</span>
                    {group.values.length > REVIEW_CAP ? (
                      <span className="s1-muted"> · {group.values.length} values from one file</span>
                    ) : null}
                    {(() => {
                      const docId = group.values[0]?.documentId;
                      // Counted by card, like the list: one reading is one accept.
                      const left = readings(
                        items.filter((x) => x.documentId === docId && x.reviewState === "to_review" && !x.withdrawn && !x.missing)
                      ).length;
                      return left > 1 && docId ? (
                        <button className="s1-button s1-button--compact s1-xr-acceptall" type="button" onClick={() => acceptAll(docId)}>
                          Accept all {left}
                        </button>
                      ) : null;
                    })()}
                  </div>
                  {(() => {
                    const docId = group.values[0]?.documentId;
                    const pages = [...new Set(nodeValues.filter((x) => x.documentId === docId).map((x) => x.page))].sort((a, b) => a - b);
                    if (pages.length < 2) return null;
                    return (
                      <div className="s1-xr-pages" role="group" aria-label="Values by page">
                        <button
                          className={`s1-xr-pagechip${pageFilter === null ? " is-on" : ""}`}
                          type="button"
                          aria-pressed={pageFilter === null}
                          onClick={() => setPageFilter(null)}
                        >
                          All pages
                        </button>
                        {pages.map((n) => (
                          <button
                            key={n}
                            className={`s1-xr-pagechip${pageFilter === n ? " is-on" : ""}`}
                            type="button"
                            aria-pressed={pageFilter === n}
                            onClick={() => {
                              setPageFilter(n);
                              const first = nodeValues.find((x) => x.documentId === docId && x.page === n);
                              if (first) setSelectedId(first.id);
                            }}
                          >
                            p.{n} <span>{nodeValues.filter((x) => x.documentId === docId && x.page === n).length}</span>
                          </button>
                        ))}
                      </div>
                    );
                  })()}
                  {capped.map((vs) => (
                    <ValueCard
                      key={vs[0].id}
                      vs={vs}
                      request={linkedAsk(vs, asks)}
                      askById={askById}
                      selected={vs.some((x) => x.id === selectedId)}
                      onSelect={() => {
                        if (!vs.some((x) => x.id === selectedId)) selectValue(vs[0]);
                      }}
                      onAccept={() => accept(vs)}
                      onCorrect={(next) => correct(vs, next)}
                      onAddToRequests={() => openAddToRequests(vs)}
                    />
                  ))}
                  {hidden > 0 ? (
                    <div className="s1-xr-more">
                      Showing {capped.length} of {cards.length}. Pick any highlighted figure on the document to open its value.
                    </div>
                  ) : null}
                </div>
              );
            })
          )}
        </div>

        {/* Source */}
        <aside className="s1-xr-source" aria-label="Source">
          <SourcePane value={selected} realPage={realPage} />
        </aside>
      </div>

      {modalTarget ? (
        <AddToRequestsModal
          target={modalTarget}
          engagement={engagement}
          onCancel={() => setModalTarget(null)}
          onAdd={submitAsk}
          serverRecordsActor={serverRecordsActor}
        />
      ) : null}

      {toast ? <div className="s1-ws-toast">{toast.message}</div> : null}
    </section>
  );
}

/* ============================ add a missed value ============================ */

function AddValueForm({
  base,
  suggestions,
  onCancel,
  onAdd,
}: {
  base: ReviewValue;
  suggestions: string[];
  onCancel: () => void;
  onAdd: (entry: { whatItIs: string; value: string; unit: string; page: number }) => void;
}) {
  const [whatItIs, setWhatItIs] = useState("");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState(base.unit);
  const [page, setPage] = useState(base.page);
  const ready = whatItIs.trim() && value.trim() && page >= 1 && page <= base.pageCount;
  return (
    <form
      className="s1-xr-addform"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) onAdd({ whatItIs: whatItIs.trim(), value: value.trim(), unit: unit.trim(), page });
      }}
    >
      <div className="s1-xr-addform__title">
        A value the reading missed on <strong>{base.filename}</strong>
      </div>
      <label className="s1-xr-addform__what">
        <span>What it is</span>
        <input list="s1-xr-addform-suggestions" value={whatItIs} autoFocus onChange={(e) => setWhatItIs(e.target.value)} placeholder="e.g. Peak demand" />
        <datalist id="s1-xr-addform-suggestions">
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      </label>
      <label>
        <span>Value</span>
        <input value={value} inputMode="decimal" onChange={(e) => setValue(e.target.value)} />
      </label>
      <label>
        <span>Unit</span>
        <input value={unit} onChange={(e) => setUnit(e.target.value)} />
      </label>
      <label>
        <span>Page</span>
        <input type="number" min={1} max={base.pageCount} value={page} onChange={(e) => setPage(Number(e.target.value))} />
      </label>
      <div className="s1-xr-addform__actions">
        <button className="s1-button s1-button--pri s1-button--compact" type="submit" disabled={!ready}>
          Add value
        </button>
        <button className="s1-linklike" type="button" onClick={onCancel}>
          Cancel
        </button>
        <span className="s1-xr-addform__note">Recorded as keyed by you; it counts as reviewed.</span>
      </div>
    </form>
  );
}

/* ============================ the document's key ============================ */

/** Pinned above the cards: what the colours on the document mean, and the switch to
 *  highlight a figure the reading missed. */
function DocumentKey({ values, highlight }: { values: ReviewValue[]; highlight?: { on: boolean; toggle: () => void } }) {
  const missing = values.filter((v) => v.missing || v.value === "not found").length;
  const read = readings(values.filter((v) => !(v.missing || v.value === "not found"))).length;
  return (
    <div className="s1-xr-key" role="group" aria-label="Highlights on the document">
      <div className="s1-xr-key__top">
        <span className="s1-xr-key__count">
          <strong>{read}</strong> {read === 1 ? "value" : "values"} read
          {missing ? (
            <>
              {" · "}
              <strong className="s1-dd-legend__miss">{missing} not found</strong>
            </>
          ) : null}
        </span>
        {highlight ? (
          <button
            className={`s1-dd-pick s1-xr-key__pick${highlight.on ? " is-on" : ""}`}
            type="button"
            aria-pressed={highlight.on}
            onClick={highlight.toggle}
          >
            <Highlighter aria-hidden /> {highlight.on ? "Done highlighting" : "Highlight a figure"}
          </button>
        ) : null}
      </div>
      <div className="s1-xr-key__keys">
        <span className="s1-dd-key s1-dd-key--to_review">To review</span>
        <span className="s1-dd-key s1-dd-key--accepted">Accepted</span>
        <span className="s1-dd-key s1-dd-key--corrected">Corrected</span>
        <span className="s1-dd-key s1-dd-key--requested">{filterLabel("requested")}</span>
        <span className="s1-dd-key s1-dd-key--missing">Not found</span>
      </div>
    </div>
  );
}

/* =============================== value card =============================== */

function ValueCard({
  vs,
  request,
  askById,
  selected,
  onSelect,
  onAccept,
  onCorrect,
  onAddToRequests,
}: {
  /** One reading: the values it feeds (two when location- and market-based share it). */
  vs: ReviewValue[];
  /** The ask the reading was added to, if any (the latest one). */
  request: Ask | null;
  askById: Map<string, Ask>;
  selected: boolean;
  onSelect: () => void;
  onAccept: () => void;
  onCorrect: (next: { value: string; unit: string }) => void;
  onAddToRequests: () => void;
}) {
  const v = vs[0];
  const done = v.reviewState !== "to_review";
  const stateLabel = valueStateLabel(v.reviewState, request);
  const [editing, setEditing] = useState(false);
  const [draftValue, setDraftValue] = useState(v.value);
  const [draftUnit, setDraftUnit] = useState(v.unit);
  const startEditing = () => {
    setDraftValue(v.value);
    setDraftUnit(v.unit);
    setEditing(true);
  };
  const changed = draftValue.trim() !== v.value || draftUnit.trim() !== v.unit;
  return (
    <article
      data-value-id={v.id}
      className={`s1-xr-card${selected ? " is-sel" : ""} s1-xr-card--${v.reviewState}${v.withdrawn ? " s1-xr-card--withdrawn" : ""}`}
      onClick={onSelect}
      tabIndex={0}
      aria-current={selected}
      onKeyDown={(e) => {
        if (e.key === "Enter" && e.target === e.currentTarget) onSelect();
      }}
    >
      <div className="s1-xr-card__top">
        <span className="s1-xr-what">{v.whatItIs}</span>
        <span className="s1-xr-period">{readablePeriod(v.period)}</span>
        {done ? <span className={`s1-xr-badge s1-xr-badge--${v.reviewState}`}>{stateLabel}</span> : null}
      </div>
      <div className="s1-xr-card__value">
        {v.missing && v.reviewState === "to_review" ? (
          <span className="s1-xr-missing">Not found on the document</span>
        ) : (
          <>
            <span className="s1-xr-val">{shown(v).value}</span>
            {shown(v).unit ? <span className="s1-xr-unit">{shown(v).unit}</span> : null}
            {v.asPrinted?.converted ? (
              <span className="s1-xr-conv">
                = {v.value}
                {v.unit ? ` ${v.unit}` : ""}, used in the calculation
              </span>
            ) : null}
          </>
        )}
        {v.reviewState === "corrected" ? (
          <span className={`s1-xr-was${v.originalValue ? "" : " s1-xr-was--keyed"}`}>
            {v.originalValue ? `was ${v.originalValue}` : "entered by the reviewer"}
          </span>
        ) : null}
      </div>
      <div className="s1-xr-card__scopes">
        {scopeChips(vs).map((chip) => (
          <span key={chip.label} className={`s1-xr-scope s1-xr-scope--${chip.scope}`}>
            {chip.label}
          </span>
        ))}
      </div>

      {/* The selected card opens: where it came from, its record, and what to do. */}
      {selected || editing ? (
        <div className="s1-xr-card__more">
          <div className="s1-xr-record">
            {v.record.map((r, i) => (
              <div key={i} className={`s1-xr-rec s1-xr-rec--${r.kind}`}>
                {r.kind === "machine" ? (
                  <span className="s1-xr-rec__mk" aria-hidden />
                ) : (
                  <span className="s1-xr-rec__who" title={r.actor}>
                    {initials(r.actor)}
                  </span>
                )}
                <span className="s1-xr-rec__act">
                  {r.kind === "machine" ? `System read · ${v.documentType}, page ${v.page}` : `${r.actor} · ${recordAction(r, askById)}`}
                </span>
                {r.reason ? <span className="s1-muted"> · {r.reason}</span> : null}
                <span className="s1-muted s1-xr-rec__at">{formatTime(r.at)}</span>
              </div>
            ))}
          </div>

        <div className="s1-xr-actions" onClick={(e) => e.stopPropagation()}>
          {v.withdrawn ? (
            <span className="s1-reason">{v.withdrawnReason ?? "Document withdrawn; actions disabled."}</span>
          ) : editing ? (
            <form
              className="s1-xr-edit"
              onSubmit={(e) => {
                e.preventDefault();
                if (!draftValue.trim() || !changed) return;
                onCorrect({ value: draftValue.trim(), unit: draftUnit.trim() });
                setEditing(false);
              }}
            >
              <label className="s1-xr-edit__field">
                <span>Value</span>
                <input autoFocus value={draftValue} onChange={(e) => setDraftValue(e.target.value)} />
              </label>
              <label className="s1-xr-edit__field s1-xr-edit__field--unit">
                <span>Unit</span>
                <input value={draftUnit} onChange={(e) => setDraftUnit(e.target.value)} />
              </label>
              <div className="s1-xr-edit__actions">
                <button className="s1-button s1-button--pri" type="submit" disabled={!draftValue.trim() || !changed}>
                  Save correction
                </button>
                <button className="s1-button" type="button" onClick={() => setEditing(false)}>
                  Cancel
                </button>
              </div>
            </form>
          ) : done ? (
            <>
              <span className="s1-muted">{stateLabel}</span>
              <button className="s1-linklike s1-xr-recorrect" type="button" onClick={startEditing}>
                Correct
              </button>
            </>
          ) : v.missing ? (
            <>
              <button className="s1-button s1-button--pri" type="button" onClick={startEditing}>
                Enter value
              </button>
              <button className="s1-button" type="button" onClick={onAddToRequests}>
                Request
              </button>
            </>
          ) : (
            <>
              <button className="s1-button s1-button--pri" type="button" onClick={onAccept}>
                Accept
              </button>
              <button className="s1-button" type="button" onClick={startEditing}>
                Correct
              </button>
              <button className="s1-button" type="button" onClick={onAddToRequests}>
                Request
              </button>
            </>
          )}
          </div>
        </div>
      ) : null}
    </article>
  );
}

/* =============================== source pane =============================== */

/** A value as its card shows it: as the document prints it, when the backend says how. */
function shown(v: ReviewValue): { value: string; unit: string } {
  return v.asPrinted ?? { value: v.value, unit: v.unit };
}

/** Every value of a document that has a position on a page, to draw as clickable boxes. */
function pageMarks(items: ReviewValue[], documentId: string): PageMark[] {
  return items
    .filter((v) => v.documentId === documentId && (v.span || v.anchor) && !v.missing && !v.withdrawn)
    .map((v) => ({ id: v.id, span: v.span ?? null, anchor: v.anchor ?? null, rawText: v.rawText ?? null,
      label: `${v.whatItIs}: ${shown(v).value}${shown(v).unit ? ` ${shown(v).unit}` : ""}`, reviewState: v.reviewState }));
}

/** What a content view (workbook, CSV, Word) needs to select values from the file. */
export interface SourcePick {
  selectedId: string;
  onPickAmong: (ids: string[]) => void;
  /** Add (or fill in) a value from a figure the reviewer highlighted on the page. */
  onAddValue?: (entry: HighlightEntry) => void;
  /** Highlight mode, switched from the values pane. */
  highlighting?: boolean;
  onHighlightingChange?: (on: boolean) => void;
}

function SourcePane({
  value,
  realPage,
}: {
  value: ReviewValue | null;
  /** The value's document as renderPage drew it; null falls back to the snippet. */
  realPage: ReactNode | null;
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
  const placed = Boolean(value.span || value.anchor);
  return (
    <div className="s1-xr-src">
      <div className="s1-xr-src-head">
        <div className="s1-xr-src-fn">{value.filename}</div>
        <div className="s1-muted">
          {realPage && value.reviewToken
            ? placed
              ? "The uploaded document, the value outlined where it was read."
              : "The uploaded document. Check the value against it."
            : realPage
              ? "Click a highlighted figure to review it."
              : value.span
              ? "Opened at the page, value highlighted."
              : "Highlight unavailable for this value."}
        </div>
        {value.sourceKind !== "text" && !realPage ? (
          <div className="s1-xr-pager">
            <button className="s1-button s1-button--compact" type="button" onClick={() => setPage(Math.max(1, page - 1))} aria-label="Previous page">
              ‹
            </button>
            <span className="s1-num s1-muted">page {page} of {value.pageCount}</span>
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
        ) : value.sourceKind === "spreadsheet" && !value.reviewToken ? (
          // The demo's drawn sheet. An uploaded file's value never shows invented rows.
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
  // Show the sheet with column letters, row numbers, a header row of titles and
  // surrounding rows, so the figure reads in context (not a bare number).
  const cols = ["A", "B", "C", "D", "E"];
  const titles = ["Date", "Trip / item", value.whatItIs || "Value", "Rate", "Amount"];
  const sample = [
    ["01 Feb", "Trip 001", "128", "$0.67", "$85.76"],
    ["03 Feb", "Trip 002", "54", "$0.67", "$36.18"],
    ["08 Feb", "Trip 003", "212", "$0.67", "$142.04"],
    ["12 Feb", "Trip 004", "77", "$0.67", "$51.59"],
    ["15 Feb", "Trip 005", "96", "$0.67", "$64.32"],
  ];
  const targetCol = value.cell?.[0] ?? "C";
  const rawRow = value.cell ? Number(value.cell.slice(1)) : 6;
  const lastRow = 1 + sample.length; // header row 1 + data rows 2..
  const targetRow = Math.min(rawRow, lastRow);

  return (
    <div className="s1-xr-sheet">
      <div className="s1-muted s1-xr-sheet__head">
        {value.filename}{value.sheet ? ` · sheet ‘${value.sheet}’` : ""} · cell {value.cell ?? "—"} outlined
      </div>
      <div className="s1-xr-sheet__scroll">
        <table className="s1-xr-sheet__table">
          <thead>
            <tr>
              <th className="s1-xr-sheet__corner" />
              {cols.map((c) => (
                <th key={c} className="s1-xr-sheet__colhead">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr className="s1-xr-sheet__titlerow">
              <th className="s1-xr-sheet__rowhead">1</th>
              {titles.map((t, i) => (
                <td key={i} className="s1-xr-sheet__title">{t}</td>
              ))}
            </tr>
            {sample.map((row, ri) => {
              const rnum = ri + 2;
              return (
                <tr key={rnum}>
                  <th className="s1-xr-sheet__rowhead">{rnum}</th>
                  {row.map((cell, ci) => {
                    const isTarget = cols[ci] === targetCol && rnum === targetRow;
                    return (
                      <td key={ci} className={isTarget ? "is-target" : ""}>
                        {isTarget ? `${value.value} ${value.unit}` : cell}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {value.cell && rawRow > lastRow ? (
        <div className="s1-muted s1-xr-sheet__note">Row {value.cell.slice(1)} shown near the header for context.</div>
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
  nodeKeyHint: string | undefined,
  valueId?: string
): { nodeKey: string; valueId: string | null; rootKey: string | null } {
  if (!items.length) return { nodeKey: "", valueId: null, rootKey: null };
  const byValue = valueId ? items.find((v) => v.id === valueId) : undefined;
  if (byValue) return { nodeKey: nodeKeyForValue(byValue), valueId: byValue.id, rootKey: rootKeyOf(byValue) };
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

/**
 * One reading of a document can feed several data points: an electricity bill's kWh is
 * both Scope 2 location-based and market-based. Values with the same figure, from the same
 * spot, in the same review state are one card, reviewed together.
 */
function readingKey(v: ReviewValue): string {
  const at = v.span ? `${v.span.page}:${v.span.x.toFixed(3)},${v.span.y.toFixed(3)}` : (v.docAnchor ?? "");
  return [v.documentId, v.whatItIs, v.value, v.unit, v.page, v.period, at, v.reviewState, v.missing ? "missing" : "", v.withdrawn ? "withdrawn" : ""].join("|");
}

function readings(values: ReviewValue[]): ReviewValue[][] {
  const map = new Map<string, ReviewValue[]>();
  for (const v of values) {
    const key = readingKey(v);
    const same = map.get(key);
    if (same) same.push(v);
    else map.set(key, [v]);
  }
  return [...map.values()];
}

/** The scopes a reading feeds, as chips: location- and market-based share one, whether they
 *  come as two values (the demo) or one value placed in both (a backend quantity). */
function scopeChips(vs: ReviewValue[]): { scope: ScopePlacement; label: string }[] {
  const scopes = distinct(
    vs.flatMap((v) => (v.scope === "scope2_both" ? ["scope2_location", "scope2_market"] : [v.scope]))
  ) as ScopePlacement[];
  if (scopes.includes("scope2_location") && scopes.includes("scope2_market")) {
    return [
      { scope: "scope2_location", label: "Scope 2 · location- and market-based" },
      ...scopes.filter((s) => s !== "scope2_location" && s !== "scope2_market").map((scope) => ({ scope, label: SCOPE_LABEL[scope] })),
    ];
  }
  return scopes.map((scope) => ({ scope, label: SCOPE_LABEL[scope] }));
}

function scopeLabels(vs: ReviewValue[]): string[] {
  return scopeChips(vs).map((chip) => chip.label);
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

/** The filter bar and the document's key. The last bucket holds every value added to
 *  requests, sent or not, so it says "Requests", not "Requested". */
function filterLabel(s: ValueReviewState): string {
  return s === "requested" ? "Requests" : reviewStateLabel(s);
}

/** The ask a reading was added to: the latest one raised from its card. A follow-up keeps
 *  the field it came from, so it counts as the reading's latest request. */
function linkedAsk(vs: ReviewValue[], asks: Ask[]): Ask | null {
  const ids = new Set(vs.map((v) => v.id));
  let latest: Ask | null = null;
  for (const a of asks) {
    if (a.source.origin !== "review_value" || !a.source.fieldKey || !ids.has(a.source.fieldKey)) continue;
    if (!latest || a.raisedAt >= latest.raisedAt) latest = a;
  }
  return latest;
}

/** The client was asked once the ask went out in a request, whatever happened to it since. */
function wasSent(ask: Ask): boolean {
  return ask.requestNumber != null || ask.history.some((e) => e.kind === "sent");
}

/** A card's state chip. A value added to requests says where its request stands: the
 *  client is only "Requested" once the request was sent. */
function valueStateLabel(state: ValueReviewState, ask: Ask | null): string {
  if (state !== "requested" || !ask) return reviewStateLabel(state);
  if (ask.state === "not_yet_sent") return "Request not sent";
  if (ask.state === "requested") return "Requested";
  if (ask.state === "resolved") return "Request resolved";
  return "Request withdrawn";
}

/** A record line. The entry that added a value to requests reads "requested from client"
 *  only once its request was sent. */
function recordAction(r: ValueRecordEntry, askById: Map<string, Ask>): string {
  const ask = r.askId ? askById.get(r.askId) : undefined;
  if (!ask) return r.action;
  return wasSent(ask) ? "requested from client" : "added to requests";
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** "Thanishque Harshaa" -> "TH"; "claire@acme.com" -> "C". */
function initials(name: string): string {
  const base = name.includes("@") ? name.split("@")[0] : name;
  const parts = base.split(/[\s._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : (parts[0] ?? "?").slice(0, 2)).toUpperCase();
}

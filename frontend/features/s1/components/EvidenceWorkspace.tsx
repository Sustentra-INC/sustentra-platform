"use client";

import { ChevronRight, Send, StickyNote, Upload } from "lucide-react";
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { createAuditIntent, type AuditIntentAction, type SessionAuditEntry } from "../utils/auditIntent";
import type {
  Ask,
  ContainerState,
  EngagementConfig,
  EvidenceItem,
  NoteEntry,
  RequestType,
} from "../types";
import type { QualityCheck } from "../api/recalculation";
import { qualityIssueLines } from "./QualityChecksPanel";
import { AddToRequestsModal, type AddToRequestsTarget } from "./AddToRequestsModal";
import { formatPeriod } from "../utils/formatPeriod";
import type { AskDraft } from "../requests/requestsStore";

/**
 * Evidence Workspace (screen 2), built to the 09/16 revision. One table, one
 * row per file, grouped by document type. Columns: Document · Facility ·
 * Document type · Processing state · Issue · Add to requests · Notes · menu.
 *
 * Note on two spec contradictions handled here (flagged to the team):
 *  - The revision lists both a "Needs you" column and an "Issue" column. We
 *    implement Issue (the more specific, revision version) and keep the fuller
 *    page-3 Menu. The "needs you" idea survives only as a header count-filter.
 *  - Processing state's spec labels (uploading · extracting · partially
 *    extracted · withdrawn) are a display mapping over the existing enum; we did
 *    not migrate the core ProcessingState enum (it feeds the backend seam).
 */

/**
 * Client-prepared inventory documents. These are what the client assembled for
 * their own inventory — not primary source evidence — so they are grouped first
 * and their category header band is coloured differently, letting the verifier
 * tell the two families apart at a glance.
 */
const CLIENT_PREPARED_TYPES: readonly string[] = [
  "Inventory workbook",
  "Organizational boundary statement",
  "Emission factor source list",
  "Facility list",
  "Prior-year inventory or report",
];
const CLIENT_PREPARED_SET = new Set(CLIENT_PREPARED_TYPES);
/** On the bird's-eye view the client-prepared documents share one bar. */
const CLIENT_PREPARED_GROUP = "Client-prepared documents";

/** Canonical type vocabulary (grouping order). "Type unresolved" sits first,
 *  then the client-prepared inventory documents, then the source evidence. */
const TYPE_ORDER: string[] = [
  "Type unresolved",
  ...CLIENT_PREPARED_TYPES,
  "Electricity bill",
  "Natural gas bill",
  "Other fuel invoice",
  "Fleet fuel statement",
  "Refrigerant service log or refrigerant purchase invoice",
  "Meter reading or meter photo",
  "Energy management system export",
  "Renewable energy certificate or retirement statement",
  "Power purchase agreement or supplier contract",
  "Supplier-specific factor documentation",
  // Not in the canonical vocabulary yet — real classes from customer calls.
  // TODO(reconcile): fold these into the canonical vocabulary before it's final.
  "Mileage or expense report",
  "Supplier roster",
];

const SET_TYPE_OPTIONS = TYPE_ORDER.filter((type) => type !== "Type unresolved");

interface EvidenceWorkspaceProps {
  engagement: EngagementConfig;
  evidence: EvidenceItem[];
  asks: Ask[];
  onSaveAsk: (draft: AskDraft) => void;
  onResolveAsk?: (askId: string) => void;
  /** Lifts manual edits (set type/facility, note, withdraw, mark relationship)
   *  to app state so they survive navigation. Same pattern as the other stores. */
  onEvidenceChange: (updater: (cur: EvidenceItem[]) => EvidenceItem[]) => void;
  onOpenExtraction: (documentId: string) => void;
  onOpenRequests?: () => void;
  onOpenSetup?: () => void;
  onUploadFiles?: (files: FileList) => void;
  /** Opens the upload pop-up. */
  onOpenUpload?: () => void;
  isUploading?: boolean;
  writesEnabled?: boolean;
  /** Types the reviewer can set (backend mode: the types the backend can read). */
  typeOptions?: string[];
  /** Data quality checks (duplicates, overlaps, cross-year bills) shown in the Issue column. */
  qualityChecks?: QualityCheck[];
  backendError?: string | null;
  demoState?: ContainerState;
  auditIntents?: SessionAuditEntry[];
  onAuditIntent?: (intent: SessionAuditEntry) => void;
}

type FacilityFilter = string | "multiple" | "none" | "unknown" | null;
type HeaderFilter = "needs" | "arrived" | "blocked" | null;

export function EvidenceWorkspace({
  engagement,
  evidence,
  asks,
  onSaveAsk,
  onResolveAsk,
  onEvidenceChange,
  onOpenExtraction,
  onOpenRequests,
  onOpenSetup,
  onUploadFiles,
  onOpenUpload,
  isUploading = false,
  writesEnabled = true,
  typeOptions = SET_TYPE_OPTIONS,
  qualityChecks,
  backendError,
  demoState,
  auditIntents = [],
  onAuditIntent,
}: EvidenceWorkspaceProps) {
  // Evidence data lives in app state (via onEvidenceChange); filters/menus below
  // are local, ephemeral UI. So manual edits survive navigation.
  const items = evidence;
  const [facilityFilter, setFacilityFilter] = useState<FacilityFilter>(null);
  const [headerFilter, setHeaderFilter] = useState<HeaderFilter>(null);
  // Bird's-eye by default: every type starts folded to its summary bar.
  const [openTypes, setOpenTypes] = useState<Set<string>>(new Set());
  const toggleType = (t: string) =>
    setOpenTypes((s) => {
      const n = new Set(s);
      if (n.has(t)) n.delete(t);
      else n.add(t);
      return n;
    });
  const [dragging, setDragging] = useState(false);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<string[]>([]);
  const [editing, setEditing] = useState<{ id: string; field: "type" | "facility" } | null>(null);
  const [noteFor, setNoteFor] = useState<string | null>(null);
  // "Mark duplicate of…" / "Mark supersedes…": the document being related, and to which file.
  const [relateFor, setRelateFor] = useState<{ documentId: string; kind: "duplicate" | "supersedes" } | null>(null);
  const [relateTarget, setRelateTarget] = useState("");
  const [noteDraft, setNoteDraft] = useState("");
  const [modalDoc, setModalDoc] = useState<EvidenceItem | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | null>(null);

  function flash(message: string) {
    setToast(message);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 2400);
  }

  const active = useMemo(() => items.filter((i) => i.disposition === "active"), [items]);

  // --- counts (withdrawn rows are out of every count) ---
  const facilityCounts = useMemo(() => {
    const map = new Map<string, number>();
    for (const f of engagement.facilities) map.set(f.facilityId, 0);
    let multiple = 0;
    let none = 0;
    let unknown = 0;
    for (const item of active) {
      if (item.facilityState === "resolved" && item.facilityId) {
        map.set(item.facilityId, (map.get(item.facilityId) ?? 0) + 1);
      } else if (item.facilityState === "multiple") {
        multiple += 1;
        // A multi-facility file also counts under each facility it covers.
        for (const fid of item.facilityIds ?? []) {
          if (map.has(fid)) map.set(fid, (map.get(fid) ?? 0) + 1);
        }
      } else if (item.facilityState === "not_facility_scoped") none += 1;
      else unknown += 1;
    }
    return { map, multiple, none, unknown };
  }, [active, engagement.facilities]);

  const headerCounts = useMemo(
    () => ({
      needs: active.filter(needsYou).length,
      arrived: active.filter((i) => i.arrivedSinceLastVisit).length,
      blocked: active.filter((i) => i.processingState === "blocked").length,
    }),
    [active]
  );

  const filtered = useMemo(() => {
    return items.filter((item) => {
      if (facilityFilter) {
        if (facilityFilter === "multiple" && item.facilityState !== "multiple") return false;
        if (facilityFilter === "none" && item.facilityState !== "not_facility_scoped") return false;
        if (facilityFilter === "unknown" && item.facilityState !== "unresolved") return false;
        if (facilityFilter !== "multiple" && facilityFilter !== "none" && facilityFilter !== "unknown") {
          // A file belongs to a facility if it resolves to it OR covers it
          // (a multi-facility file appears under every facility it covers).
          const covers = item.facilityId === facilityFilter || (item.facilityIds ?? []).includes(facilityFilter);
          if (!covers) return false;
        }
      }
      if (headerFilter === "needs" && !needsYou(item)) return false;
      if (headerFilter === "arrived" && !item.arrivedSinceLastVisit) return false;
      if (headerFilter === "blocked" && item.processingState !== "blocked") return false;
      return true;
    });
  }, [items, facilityFilter, headerFilter]);

  const groups = useMemo(() => groupByType(filtered), [filtered]);
  const hasFilter = facilityFilter !== null || headerFilter !== null;
  const activeCount = active.length;

  // --- writes (all real, recorded via audit intents) ---
  function record(action: AuditIntentAction, documentId: string, oldValue: string | null, newValue: string | null) {
    onAuditIntent?.(createAuditIntent({ action, documentId, oldValue, newValue }));
  }

  function setType(documentId: string, nextType: string) {
    const prev = items.find((i) => i.documentId === documentId)?.detectedType ?? null;
    onEvidenceChange((cur) =>
      cur.map((i) =>
        i.documentId === documentId
          ? { ...i, detectedType: nextType, typeReviewBand: null, typeReviewReason: null, typeConfirmed: true }
          : i
      )
    );
    setEditing(null);
    record("set_type", documentId, prev, nextType);
    flash(prev === nextType ? `Type confirmed: ${nextType}` : `Type set to ${nextType}`);
  }

  function setFacility(documentId: string, facilityId: string) {
    const facility = engagement.facilities.find((f) => f.facilityId === facilityId);
    if (!facility) return;
    onEvidenceChange((cur) =>
      cur.map((i) =>
        i.documentId === documentId
          ? { ...i, facilityState: "resolved", facilityId: facility.facilityId, facilityName: facility.name }
          : i
      )
    );
    setEditing(null);
    record("set_facility", documentId, null, facility.name);
    flash(`Facility set to ${facility.name}`);
  }

  function addNote(documentId: string) {
    const text = noteDraft.trim();
    if (!text) return;
    const now = new Date();
    const entry: NoteEntry = {
      id: `n-${documentId}-${now.getTime()}`,
      author: raisedByDefault(engagement).name,
      at: now.toISOString(),
      text,
    };
    onEvidenceChange((cur) =>
      cur.map((i) =>
        i.documentId === documentId ? { ...i, note: text, notes: [...(i.notes ?? []), entry] } : i
      )
    );
    setNoteFor(null);
    setNoteDraft("");
    record("add_note", documentId, null, text);
    flash("Note added");
  }

  function markRelationship(documentId: string, kind: "duplicate" | "supersedes") {
    setRelateFor({ documentId, kind });
    setRelateTarget("");
  }

  function saveRelationship() {
    if (!relateFor) return;
    const { documentId, kind } = relateFor;
    const target = items.find((i) => i.documentId === relateTarget);
    if (!target) return;
    setRelateFor(null);
    onEvidenceChange((cur) =>
      cur.map((i) =>
        i.documentId === documentId
          ? { ...i, relationships: [...i.relationships, { kind, otherDocumentId: target.documentId }] }
          : i
      )
    );
    record(kind === "duplicate" ? "mark_duplicate" : "mark_supersedes", documentId, null, target.filename);
    flash(`Marked ${kind === "duplicate" ? "duplicate of" : "supersedes"} ${target.filename}`);
  }

  function answersRequest(documentId: string) {
    const ask = latestAsk(asks, documentId);
    if (!ask || ask.state !== "requested") {
      flash("No open request on this file to resolve");
      return;
    }
    onResolveAsk?.(ask.id);
    record("answers_request", documentId, `request ${ask.requestNumber}`, "resolved");
    flash(`Resolved request ${ask.requestNumber}`);
  }

  function withdraw(documentId: string) {
    const item = items.find((i) => i.documentId === documentId);
    if (!item) return;
    if (!window.confirm(`Withdraw ${item.filename}? The row stays, greyed, and the action is logged.`)) return;
    onEvidenceChange((cur) => cur.map((i) => (i.documentId === documentId ? { ...i, disposition: "withdrawn" } : i)));
    record("withdraw_document", documentId, "active", "withdrawn");
    flash(`Withdrew ${item.filename}`);
  }

  function reinstate(documentId: string) {
    onEvidenceChange((cur) => cur.map((i) => (i.documentId === documentId ? { ...i, disposition: "active" } : i)));
    record("reinstate_document", documentId, "withdrawn", "active");
  }

  function submitAsk(draft: AskDraft) {
    onSaveAsk(draft);
    setModalDoc(null);
    flash("Added to requests · not yet sent");
  }

  const showEmpty = activeCount === 0;
  const showFilteredEmpty = !showEmpty && filtered.length === 0;

  return (
    <section
      className={`s1-content s1-ws${dragging ? " s1-ws--drag" : ""}`}
      onDragOver={(e) => {
        if (!onUploadFiles || !Array.from(e.dataTransfer.types).includes("Files")) return;
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
        setDragging(false);
      }}
      onDrop={(e) => {
        if (!onUploadFiles || !e.dataTransfer.files.length) return;
        e.preventDefault();
        setDragging(false);
        onUploadFiles(e.dataTransfer.files);
      }}
    >
      {dragging ? (
        <div className="s1-ws-dropveil" aria-hidden>
          <span>Drop to upload</span>
        </div>
      ) : null}
      <WorkspaceHeader
        total={activeCount}
        counts={headerCounts}
        activeFilter={headerFilter}
        onFilter={(f) => setHeaderFilter((cur) => (cur === f ? null : f))}
        onUpload={onOpenUpload}
      />

      {backendError ? (
        <div className="s1-system-banner" role="status">
          <strong>Backend call failed</strong>
          <span>{backendError}</span>
        </div>
      ) : null}

      {showEmpty ? (
        <FirstDayEmpty onUploadFiles={onUploadFiles} isUploading={isUploading} />
      ) : (
        <>
          <FacilityFilterStrip
            engagement={engagement}
            counts={facilityCounts}
            active={facilityFilter}
            onSelect={(f) => setFacilityFilter((cur) => (cur === f ? null : f))}
          />

          {showFilteredEmpty ? (
            <div className="s1-ws-empty" role="status">
              <p>No files match {describeFilter(facilityFilter, headerFilter, engagement)}.</p>
              <button
                className="s1-button"
                type="button"
                onClick={() => {
                  setFacilityFilter(null);
                  setHeaderFilter(null);
                }}
              >
                Clear filter
              </button>
            </div>
          ) : (
            <div className="s1-ws-groups">
              {groups.map((group) => {
                // A filter shows its matches; otherwise a type opens on click.
                const open = hasFilter || openTypes.has(group.type);
                const prepared = group.type === CLIENT_PREPARED_GROUP;
                const mix = statusMix(group.items);
                return (
                  <section key={group.type} className={`s1-ws-gr${open ? " is-open" : ""}${prepared ? " s1-ws-gr--prepared" : ""}`}>
                    <button className="s1-ws-gr__head" type="button" aria-expanded={open} onClick={() => toggleType(group.type)}>
                      <ChevronRight className="s1-ws-gr__caret" aria-hidden />
                      <span className="s1-ws-gr__type">
                        {group.type}
                        {prepared ? <span className="s1-ws-gr__tag">Inventory, not source evidence</span> : null}
                      </span>
                      <span className="s1-ws-gr__n">
                        {group.items.length} {group.items.length === 1 ? "document" : "documents"}
                      </span>
                      <span className="s1-ws-gr__bar" aria-hidden>
                        {mix.map((part) => (
                          <span key={part.role} className={`s1-ws-gr__seg s1-ws-gr__seg--${part.role}`} style={{ flexGrow: part.n }} />
                        ))}
                      </span>
                      <span className="s1-ws-gr__mix">
                        {mix.map((part) => (
                          <span key={part.role} className={`s1-ws-gr__mixitem s1-ws-gr__mixitem--${part.role}`}>
                            {part.n} {part.label}
                          </span>
                        ))}
                      </span>
                    </button>
                    {open ? (
                      <div className="s1-table-wrap s1-ws-gr__body">
                        <table className="s1-table s1-ws-table">
                          <colgroup>
                            <col style={{ width: "34%" }} /* Document */ />
                            <col style={{ width: "18%" }} /* Facility */ />
                            <col style={{ width: "20%" }} /* Type */ />
                            <col style={{ width: "22%" }} /* Status */ />
                            <col style={{ width: "6%" }} /* Menu */ />
                          </colgroup>
                          <thead>
                            <tr>
                              <th>Document</th>
                              <th>Facility</th>
                              <th>Type</th>
                              <th>Status</th>
                              <th aria-label="Actions"></th>
                            </tr>
                          </thead>
                          <tbody>
                            {group.items.map((item) => (
                              <Fragment key={item.documentId}>
                                <WorkspaceRow
                                  item={item}
                                  items={items}
                                  asks={asks}
                                  engagement={engagement}
                                  writesEnabled={writesEnabled}
                                  typeOptions={typeOptions}
                                  qualityChecks={qualityChecks}
                                  editing={editing?.id === item.documentId ? editing.field : null}
                                  menuOpen={openMenuId === item.documentId}
                                  onOpenExtraction={onOpenExtraction}
                                  onOpenRequests={() => (onOpenRequests ? onOpenRequests() : flash("Evidence requests is built next."))}
                                  onStartEdit={(field) => setEditing({ id: item.documentId, field })}
                                  onSetType={setType}
                                  onSetFacility={setFacility}
                                  onStartNote={() => {
                                    setNoteFor(item.documentId);
                                    setNoteDraft("");
                                  }}
                                  onMenu={(open) => setOpenMenuId(open ? item.documentId : null)}
                                  onToggleExpand={() =>
                                    setExpandedIds((cur) =>
                                      cur.includes(item.documentId)
                                        ? cur.filter((id) => id !== item.documentId)
                                        : [...cur, item.documentId]
                                    )
                                  }
                                  onAddToRequests={() => setModalDoc(item)}
                                  onMarkDuplicate={() => markRelationship(item.documentId, "duplicate")}
                                  onMarkSupersedes={() => markRelationship(item.documentId, "supersedes")}
                                  onAnswersRequest={() => answersRequest(item.documentId)}
                                  onWithdraw={() => withdraw(item.documentId)}
                                  onReinstate={() => reinstate(item.documentId)}
                                />
                                {noteFor === item.documentId ? (
                                  <tr className="s1-history-row">
                                    <td colSpan={5}>
                                      <NoteEditor
                                        filename={item.filename}
                                        draft={noteDraft}
                                        onDraft={setNoteDraft}
                                        onSave={() => addNote(item.documentId)}
                                        onCancel={() => setNoteFor(null)}
                                      />
                                    </td>
                                  </tr>
                                ) : null}
                                {relateFor?.documentId === item.documentId ? (
                                  <tr className="s1-history-row">
                                    <td colSpan={5}>
                                      <div className="s1-relate" role="group" aria-label={`Relate ${item.filename}`}>
                                        <label>
                                          <span>
                                            Mark {item.filename} as {relateFor.kind === "duplicate" ? "a duplicate of" : "superseding"}
                                          </span>
                                          <select value={relateTarget} onChange={(e) => setRelateTarget(e.target.value)}>
                                            <option value="">Choose a file</option>
                                            {items
                                              .filter((i) => i.documentId !== item.documentId && i.disposition === "active")
                                              .map((i) => (
                                                <option key={i.documentId} value={i.documentId}>
                                                  {i.filename}
                                                </option>
                                              ))}
                                          </select>
                                        </label>
                                        <button className="s1-button s1-button--pri" type="button" disabled={!relateTarget}
                                          onClick={saveRelationship}>
                                          Mark
                                        </button>
                                        <button className="s1-linklike" type="button" onClick={() => setRelateFor(null)}>
                                          Cancel
                                        </button>
                                      </div>
                                    </td>
                                  </tr>
                                ) : null}
                                {expandedIds.includes(item.documentId) ? (
                                  <tr className="s1-history-row">
                                    <td colSpan={5}>
                                      <RowRecord item={item} intents={auditIntents.filter((a) => a.documentId === item.documentId)} />
                                    </td>
                                  </tr>
                                ) : null}
                              </Fragment>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : null}
                  </section>
                );
              })}
            </div>
          )}
        </>
      )}

      {modalDoc ? (
        <AddToRequestsModal
          target={workspaceTarget(modalDoc)}
          engagement={engagement}
          onCancel={() => setModalDoc(null)}
          onAdd={submitAsk}
        />
      ) : null}

      {toast ? <div className="s1-ws-toast">{toast}</div> : null}
    </section>
  );
}

/* =============================== header =============================== */

function WorkspaceHeader({
  total,
  counts,
  activeFilter,
  onFilter,
  onUpload,
}: {
  total: number;
  counts: { needs: number; arrived: number; blocked: number };
  activeFilter: HeaderFilter;
  onFilter: (f: HeaderFilter) => void;
  onUpload?: () => void;
}) {
  return (
    <header className="s1-ws-header s1-ws-top">
      <div className="s1-ws-header__id">
        <h1>Evidence</h1>
        <span className="s1-ws-top__total">
          {total} {total === 1 ? "document" : "documents"}
        </span>
      </div>
      <div className="s1-ws-top__right">
        <div className="s1-ws-header__counts" role="group" aria-label="Show only">
          <CountFilter label="Need you" tone="accent" n={counts.needs} on={activeFilter === "needs"} onClick={() => onFilter("needs")} />
          <CountFilter label="New since last visit" tone="neutral" n={counts.arrived} on={activeFilter === "arrived"} onClick={() => onFilter("arrived")} />
          <CountFilter label="Blocked" tone="blocking" n={counts.blocked} on={activeFilter === "blocked"} onClick={() => onFilter("blocked")} />
        </div>
        {onUpload ? (
          <button className="s1-button s1-button--pri s1-ws-top__upload" type="button" onClick={onUpload}>
            <Upload aria-hidden /> Upload
          </button>
        ) : null}
      </div>
    </header>
  );
}

function CountFilter({
  label,
  n,
  on,
  tone = "neutral",
  onClick,
}: {
  label: string;
  n: number;
  on: boolean;
  tone?: "accent" | "blocking" | "neutral";
  onClick: () => void;
}) {
  return (
    <button
      className={`s1-ws-count s1-ws-count--${tone}${on ? " is-on" : ""}`}
      type="button"
      aria-pressed={on}
      onClick={onClick}
    >
      <span className="s1-ws-count__n">{n}</span>
      <span className="s1-ws-count__label">{label}</span>
    </button>
  );
}

function FacilityFilterStrip({
  engagement,
  counts,
  active,
  onSelect,
}: {
  engagement: EngagementConfig;
  counts: { map: Map<string, number>; multiple: number; none: number; unknown: number };
  active: FacilityFilter;
  onSelect: (f: FacilityFilter) => void;
}) {
  return (
    <div className="s1-ws-facilities" role="group" aria-label="Filter by facility">
      {engagement.facilities.map((f) => (
        <FacilityChip
          key={f.facilityId}
          label={f.name}
          n={counts.map.get(f.facilityId) ?? 0}
          on={active === f.facilityId}
          onClick={() => onSelect(f.facilityId)}
        />
      ))}
      <FacilityChip label="Multiple facilities" n={counts.multiple} on={active === "multiple"} onClick={() => onSelect("multiple")} />
      <FacilityChip label="No facility" n={counts.none} on={active === "none"} onClick={() => onSelect("none")} />
      <FacilityChip label="Not yet known" n={counts.unknown} on={active === "unknown"} onClick={() => onSelect("unknown")} />
    </div>
  );
}

function FacilityChip({ label, n, on, onClick }: { label: string; n: number; on: boolean; onClick: () => void }) {
  return (
    <button className={`s1-ws-facchip${on ? " is-on" : ""}`} type="button" aria-pressed={on} onClick={onClick}>
      {label} <span className="s1-muted">{n}</span>
    </button>
  );
}

/* =============================== row =============================== */

function WorkspaceRow(props: {
  item: EvidenceItem;
  items: EvidenceItem[];
  asks: Ask[];
  engagement: EngagementConfig;
  writesEnabled: boolean;
  typeOptions: string[];
  qualityChecks?: QualityCheck[];
  editing: "type" | "facility" | null;
  menuOpen: boolean;
  onOpenExtraction: (id: string) => void;
  onOpenRequests: () => void;
  onStartEdit: (field: "type" | "facility") => void;
  onSetType: (id: string, type: string) => void;
  onSetFacility: (id: string, facilityId: string) => void;
  onStartNote: () => void;
  onMenu: (open: boolean) => void;
  onToggleExpand: () => void;
  onAddToRequests: () => void;
  onMarkDuplicate: () => void;
  onMarkSupersedes: () => void;
  onAnswersRequest: () => void;
  onWithdraw: () => void;
  onReinstate: () => void;
}) {
  const { item, items, asks, engagement } = props;
  const withdrawn = item.disposition === "withdrawn";
  const proc = processingDisplay(item);
  const issues = [
    ...issueLines(item, items, engagement).filter((line) => line !== proc.sub),
    ...(withdrawn
      ? []
      : qualityIssueLines(props.qualityChecks, item.documentId, (id) => items.find((d) => d.documentId === id)?.filename ?? id)),
  ];
  const ask = latestAsk(asks, item.documentId);
  const notes = item.notes ?? [];
  const period = item.periodStart && item.periodEnd ? formatPeriod(item.periodStart, item.periodEnd) : null;

  return (
    <tr className={withdrawn ? "s1-row-withdrawn" : ""}>
      {/* Document: name (opens its extraction), period, and markers for notes and requests */}
      <td>
        <button className="s1-doc-link" type="button" onClick={() => props.onOpenExtraction(item.documentId)}>
          {item.filename}
        </button>
        <div className="s1-ws-docmeta">
          {period ? <span>{period}</span> : null}
          {notes.length ? (
            <button className="s1-ws-marker" type="button" onClick={props.onToggleExpand} title={notes[notes.length - 1].text}>
              <StickyNote aria-hidden /> {notes.length} {notes.length === 1 ? "note" : "notes"}
            </button>
          ) : null}
          {ask ? (
            <button className={`s1-ws-marker s1-ws-marker--${ask.state}`} type="button" onClick={props.onOpenRequests}>
              <Send aria-hidden /> {askLabel(ask)}
            </button>
          ) : null}
        </div>
      </td>

      {/* Facility: the picker sits inline while it is not known */}
      <td>
        {props.writesEnabled && (props.editing === "facility" || item.facilityState === "unresolved") ? (
          <select
            className="s1-inline-input s1-select"
            defaultValue={item.facilityId ?? ""}
            aria-label="Set facility"
            onChange={(e) => props.onSetFacility(item.documentId, e.target.value)}
          >
            <option value="" disabled>
              Choose facility
            </option>
            {engagement.facilities.map((f) => (
              <option key={f.facilityId} value={f.facilityId}>
                {f.name}
              </option>
            ))}
          </select>
        ) : (
          <FacilityCell item={item} />
        )}
      </td>

      {/* Type: the picker sits inline while it is not confirmed */}
      <td>
        {props.writesEnabled &&
        (props.editing === "type" ||
          item.detectedType == null ||
          (!item.typeConfirmed && (item.typeReviewBand === "needs_review" || item.typeReviewBand === "cannot_determine"))) ? (
          <div className="s1-ws-setcell">
            <select
              className="s1-inline-input s1-select"
              defaultValue={item.detectedType ?? ""}
              aria-label="Set document type"
              onChange={(e) => props.onSetType(item.documentId, e.target.value)}
            >
              <option value="" disabled>
                Choose type
              </option>
              {props.typeOptions.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            {item.detectedType != null && !item.typeConfirmed ? (
              <button
                className="s1-linklike s1-ws-confirm"
                type="button"
                onClick={() => props.onSetType(item.documentId, item.detectedType as string)}
              >
                Confirm this type
              </button>
            ) : null}
          </div>
        ) : (
          <span>{item.detectedType ?? "Type unresolved"}</span>
        )}
      </td>

      {/* Status: processing state, and any issue under it */}
      <td>
        <span className={`s1-state s1-state--${proc.role}`}>{proc.label}</span>
        {proc.sub || issues.length ? (
          <div className="s1-ws-issues">
            {[proc.sub, ...issues].filter(Boolean).map((line) => (
              <div key={line as string}>{line}</div>
            ))}
          </div>
        ) : null}
      </td>

      <td>
        <RowMenu
          item={item}
          hasAsk={Boolean(ask)}
          isOpen={props.menuOpen}
          onOpenChange={props.onMenu}
          onOpen={() => props.onOpenExtraction(item.documentId)}
          onAddToRequests={props.onAddToRequests}
          onOpenRequests={props.onOpenRequests}
          onSetType={() => props.onStartEdit("type")}
          onSetFacility={() => props.onStartEdit("facility")}
          onAddNote={props.onStartNote}
          onMarkDuplicate={props.onMarkDuplicate}
          onMarkSupersedes={props.onMarkSupersedes}
          onAnswersRequest={props.onAnswersRequest}
          onWithdraw={props.onWithdraw}
          onReinstate={props.onReinstate}
          onHistory={props.onToggleExpand}
        />
      </td>
    </tr>
  );
}

function askLabel(ask: Ask): string {
  if (ask.state === "not_yet_sent") return "In requests, not sent";
  if (ask.state === "requested") return `Requested · #${ask.requestNumber}`;
  if (ask.state === "resolved") return "Request resolved";
  return "Request withdrawn";
}

/** The type group's mix, one bucket per document, most urgent first. */
function statusMix(items: EvidenceItem[]): Array<{ role: string; label: string; n: number }> {
  const buckets = [
    { role: "blocking", label: "blocked", n: 0 },
    { role: "open", label: "need you", n: 0 },
    { role: "active", label: "extracting", n: 0 },
    { role: "resolved", label: "extracted", n: 0 },
    { role: "na", label: "withdrawn", n: 0 },
  ];
  const bump = (role: string) => {
    const bucket = buckets.find((b) => b.role === role);
    if (bucket) bucket.n += 1;
  };
  for (const item of items) {
    if (item.disposition === "withdrawn") bump("na");
    else if (item.processingState === "blocked") bump("blocking");
    else if (needsYou(item)) bump("open");
    else if (item.processingState === "extracted") bump("resolved");
    else bump("active");
  }
  return buckets.filter((b) => b.n > 0);
}

function FacilityCell({ item }: { item: EvidenceItem }) {
  if (item.facilityState === "resolved") {
    return (
      <span title={item.facilitySource === "reviewer" ? "Chosen by the reviewer" : "Matched by name or address"}>
        {item.facilityName}
      </span>
    );
  }
  if (item.facilityState === "multiple") return <span>{item.facilityCount ?? 2} facilities</span>;
  if (item.facilityState === "not_facility_scoped") return <span title="Entity-level document">No facility</span>;
  return <span className="s1-muted">Not yet known</span>;
}

function NoteEditor({
  filename,
  draft,
  onDraft,
  onSave,
  onCancel,
}: {
  filename: string;
  draft: string;
  onDraft: (v: string) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="s1-ws-noteedit">
      <input
        className="s1-inline-input"
        value={draft}
        autoFocus
        aria-label={`Note on ${filename}`}
        placeholder={`Note on ${filename}`}
        onChange={(e) => onDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") onSave();
          if (e.key === "Escape") onCancel();
        }}
      />
      <button className="s1-button s1-button--pri s1-button--compact" type="button" disabled={!draft.trim()} onClick={onSave}>
        Save note
      </button>
      <button className="s1-linklike" type="button" onClick={onCancel}>
        Cancel
      </button>
    </div>
  );
}

function RowMenu({
  item,
  hasAsk,
  isOpen,
  onOpenChange,
  onOpen,
  onAddToRequests,
  onOpenRequests,
  onSetType,
  onSetFacility,
  onAddNote,
  onMarkDuplicate,
  onMarkSupersedes,
  onAnswersRequest,
  onWithdraw,
  onReinstate,
  onHistory,
}: {
  item: EvidenceItem;
  hasAsk: boolean;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onOpen: () => void;
  onAddToRequests: () => void;
  onOpenRequests: () => void;
  onSetType: () => void;
  onSetFacility: () => void;
  onAddNote: () => void;
  onMarkDuplicate: () => void;
  onMarkSupersedes: () => void;
  onAnswersRequest: () => void;
  onWithdraw: () => void;
  onReinstate: () => void;
  onHistory: () => void;
}) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const withdrawn = item.disposition === "withdrawn";
  // Where the floating menu opens: under the button, or above it near the bottom of the window.
  const [place, setPlace] = useState<{ top: number; left: number; up: boolean } | null>(null);
  useLayoutEffect(() => {
    if (!isOpen || !triggerRef.current) {
      setPlace(null);
      return;
    }
    const measure = () => {
      const box = triggerRef.current?.getBoundingClientRect();
      if (!box) return;
      const height = menuRef.current?.offsetHeight ?? 320;
      const width = menuRef.current?.offsetWidth ?? 208;
      const up = box.bottom + height + 8 > window.innerHeight && box.top - height - 8 > 0;
      setPlace({ top: up ? box.top - height - 4 : box.bottom + 4, left: Math.max(8, box.right - width), up });
    };
    measure();
    const frame = window.requestAnimationFrame(measure); // again once the menu has its size
    window.addEventListener("scroll", measure, true);
    window.addEventListener("resize", measure);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("resize", measure);
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    function onDown(e: PointerEvent) {
      const t = e.target as Node;
      if (menuRef.current?.contains(t) || triggerRef.current?.contains(t)) return;
      onOpenChange(false);
    }
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [isOpen, onOpenChange]);

  const entries: Array<{ label: string; action: () => void; disabled?: boolean }> = withdrawn
    ? [
        { label: "Open", action: onOpen },
        { label: "History", action: onHistory },
        { label: "Reinstate document", action: onReinstate },
      ]
    : [
        { label: "Open extraction", action: onOpen },
        hasAsk ? { label: "View in requests", action: onOpenRequests } : { label: "Add to requests", action: onAddToRequests },
        { label: "Set type", action: onSetType },
        { label: "Set facility", action: onSetFacility },
        { label: "Add note", action: onAddNote },
        { label: "Mark duplicate of…", action: onMarkDuplicate },
        { label: "Mark supersedes…", action: onMarkSupersedes },
        { label: "Answers request", action: onAnswersRequest },
        { label: "History", action: onHistory },
        { label: "Withdraw", action: onWithdraw },
      ];

  return (
    <div className="s1-menu">
      <button
        ref={triggerRef}
        className="s1-button s1-button--icon"
        type="button"
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-label={`Actions for ${item.filename}`}
        onClick={() => onOpenChange(!isOpen)}
      >
        ⋯
      </button>
      {isOpen && place
        ? createPortal(
        <div
          className="s1-menu__panel s1-menu__panel--float"
          role="menu"
          ref={menuRef}
          style={{ top: place.top, left: place.left, transformOrigin: place.up ? "bottom right" : "top right" }}
        >
          {entries.map((entry) => (
            <button
              key={entry.label}
              className="s1-menu__item"
              type="button"
              role="menuitem"
              disabled={entry.disabled}
              onClick={() => {
                entry.action();
                onOpenChange(false);
              }}
            >
              {entry.label}
            </button>
          ))}
        </div>,
            document.querySelector(".s1-app") ?? document.body
          )
        : null}
    </div>
  );
}

/* ======================= Add to requests target ======================= */

function workspaceTarget(item: EvidenceItem): AddToRequestsTarget {
  const facility = facilityLabel(item);
  const period = periodLabel(item);
  const arrival = item.answeredRequestNumber != null ? `Answered request ${item.answeredRequestNumber}` : "Uploaded";
  return {
    origin: "workspace_document",
    documentId: item.documentId,
    itemLabel: item.filename,
    facilityName: item.facilityName,
    period,
    arrival,
    headerLine: `${item.filename} · ${facility} · ${arrival} · ${formatDate(item.uploadedAt)}`,
    defaultType: preselectType(item),
    prefill: `${item.filename} · ${facility} · ${period}: `,
  };
}

/* =============================== states =============================== */

function FirstDayEmpty({ onUploadFiles, isUploading }: { onUploadFiles?: (files: FileList) => void; isUploading: boolean }) {
  const [drag, setDrag] = useState(false);
  return (
    <div
      className={`s1-band s1-upload s1-ws-firstday ${drag ? "s1-upload--drag" : ""} ${isUploading ? "s1-upload--busy" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        if (e.dataTransfer.files.length && onUploadFiles) onUploadFiles(e.dataTransfer.files);
      }}
    >
      <div>
        <h3>No documents yet</h3>
        <div className="s1-muted">Drop the client&rsquo;s package here to start. Each file appears as a row as it uploads.</div>
      </div>
      <label className="s1-button">
        {isUploading ? "Uploading" : "Choose files"}
        <input
          className="s1-file-input"
          type="file"
          multiple
          onChange={(e) => {
            if (e.target.files?.length && onUploadFiles) onUploadFiles(e.target.files);
          }}
        />
      </label>
    </div>
  );
}

function RowRecord({ item, intents }: { item: EvidenceItem; intents: SessionAuditEntry[] }) {
  const notes = item.notes ?? [];
  return (
    <div className="s1-ws-record">
      {notes.length > 0 ? (
        <div className="s1-ws-record__notes">
          <strong>Notes</strong>
          {notes.map((n) => (
            <div key={n.id}>
              <span className="s1-mono s1-muted">
                {n.author} · {formatDate(n.at)}
              </span>{" "}
              {n.text}
            </div>
          ))}
        </div>
      ) : null}
      <div className="s1-ws-record__log">
        <strong>History</strong>
        <div>
          <span className="s1-mono s1-muted">
            {item.uploadedBy.name} · {formatDate(item.uploadedAt)}
          </span>{" "}
          {item.answeredRequestNumber != null ? `uploaded it, answering request ${item.answeredRequestNumber}` : "uploaded it"}
        </div>
        {intents.length === 0 ? null : (
          [...intents].reverse().map((a) => (
            <div key={a.entryId}>
              <span className="s1-mono s1-muted">
                {a.actor.name} · {new Date(a.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </span>{" "}
              {a.action.replaceAll("_", " ")}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/* =============================== helpers =============================== */

function groupByType(items: EvidenceItem[]): Array<{ type: string; items: EvidenceItem[] }> {
  const map = new Map<string, EvidenceItem[]>();
  for (const item of items) {
    const detected = item.detectedType ?? "Type unresolved";
    const type = CLIENT_PREPARED_SET.has(detected) ? CLIENT_PREPARED_GROUP : detected;
    map.set(type, [...(map.get(type) ?? []), item]);
  }
  const order = (t: string) => {
    if (t === CLIENT_PREPARED_GROUP) return 0.5; // after "Type unresolved"
    const i = TYPE_ORDER.indexOf(t);
    return i === -1 ? TYPE_ORDER.length : i;
  };
  return Array.from(map.entries())
    .map(([type, group]) => ({ type, items: sortDocs(group) }))
    .sort((a, b) => order(a.type) - order(b.type));
}

function sortDocs(items: EvidenceItem[]): EvidenceItem[] {
  return [...items].sort((a, b) => (a.periodStart ?? "").localeCompare(b.periodStart ?? ""));
}

function needsYou(item: EvidenceItem): boolean {
  if (item.disposition !== "active") return false;
  if (item.processingState === "blocked") return true;
  if (item.detectedType == null || item.typeReviewBand === "cannot_determine" || item.typeReviewBand === "needs_review")
    return true;
  if (item.facilityState === "unresolved") return true;
  if (item.relationships.length > 0) return true;
  if (item.processingState === "extracted" && item.fieldsExpectedDisplay != null && item.fieldsExtracted < item.fieldsExpectedDisplay)
    return true;
  return false;
}

function processingDisplay(item: EvidenceItem): { role: string; label: string; sub: string | null } {
  if (item.disposition === "withdrawn") return { role: "na", label: "Withdrawn", sub: null };
  if (item.processingState === "blocked") return { role: "blocking", label: "Blocked", sub: item.haltReason };
  if (
    item.processingState === "extracted" &&
    item.fieldsExpectedDisplay != null &&
    item.fieldsExtracted < item.fieldsExpectedDisplay
  ) {
    const missing = item.missingFields && item.missingFields.length > 0 ? item.missingFields.join(", ") : null;
    return {
      role: "open",
      label: "Partially extracted",
      sub: missing ? `Not found: ${missing}` : `${item.fieldsExtracted} of ${item.fieldsExpectedDisplay} fields`,
    };
  }
  if (item.processingState === "extracted") return { role: "resolved", label: "Extracted", sub: null };
  if (item.processingState === "typed" || item.processingState === "ingested")
    return { role: "active", label: "Extracting", sub: null };
  return { role: "active", label: "Uploading", sub: null };
}

function issueLines(item: EvidenceItem, all: EvidenceItem[], engagement: EngagementConfig): string[] {
  if (item.disposition === "withdrawn") return [];
  const lines: string[] = [];
  if (item.processingState === "blocked" && item.haltReason) lines.push(item.haltReason);
  if (
    item.processingState === "extracted" &&
    item.fieldsExpectedDisplay != null &&
    item.fieldsExtracted < item.fieldsExpectedDisplay &&
    item.missingFields &&
    item.missingFields.length > 0
  ) {
    lines.push(`Not found: ${item.missingFields.join(", ")}`);
  }
  for (const rel of item.relationships) {
    const other = all.find((d) => d.documentId === rel.otherDocumentId);
    const name = other?.filename ?? rel.otherDocumentId;
    if (rel.kind === "duplicate") lines.push(`Duplicate of ${name}`);
    else if (rel.kind === "conflicting_value") lines.push(`Conflicts with ${name}`);
    else if (rel.kind === "supersedes") lines.push(`Supersedes ${name}`);
    else if (rel.kind === "superseded_by") lines.push(`Superseded by ${name}`);
  }
  if (periodOutsideYear(item, engagement)) lines.push("Period outside reporting year");
  return lines;
}

function periodOutsideYear(item: EvidenceItem, engagement: EngagementConfig): boolean {
  if (item.periodState !== "resolved" || !item.periodStart || !item.periodEnd) return false;
  return item.periodEnd < engagement.reportingPeriod.start || item.periodStart > engagement.reportingPeriod.end;
}

function latestAsk(asks: Ask[], documentId: string): Ask | null {
  const forDoc = asks.filter((a) => a.source.documentId === documentId);
  return forDoc.length ? forDoc[forDoc.length - 1] : null;
}

function preselectType(item: EvidenceItem): RequestType {
  if (
    item.processingState === "blocked" ||
    (item.processingState === "extracted" &&
      item.fieldsExpectedDisplay != null &&
      item.fieldsExtracted < item.fieldsExpectedDisplay) ||
    item.periodStart != null && item.periodStart < "2025-01-01"
  ) {
    return "replace_document";
  }
  // On a clean extracted row nothing is missing; the verifier is asking about
  // something she doubts.
  return "clarify";
}

function facilityLabel(item: EvidenceItem): string {
  if (item.facilityState === "resolved") return item.facilityName ?? "facility";
  if (item.facilityState === "multiple") return "multiple facilities";
  if (item.facilityState === "not_facility_scoped") return "entity-level";
  return "not yet known";
}

function periodLabel(item: EvidenceItem): string {
  if (item.periodStart && item.periodEnd) return formatPeriod(item.periodStart, item.periodEnd);
  if (item.periodState === "spans_multiple") return "spans multiple periods";
  return "period not yet known";
}

function raisedByDefault(engagement: EngagementConfig) {
  const team = engagement.engagementTeam ?? [];
  const signed = team.find((m) => m.login === engagement.signedInLogin);
  return signed ?? team[0] ?? { name: "You", login: "you" };
}

function describeFilter(facility: FacilityFilter, header: HeaderFilter, engagement: EngagementConfig): string {
  const parts: string[] = [];
  if (facility) {
    if (facility === "multiple") parts.push("Multiple facilities");
    else if (facility === "none") parts.push("No facility");
    else if (facility === "unknown") parts.push("Not yet known");
    else parts.push(engagement.facilities.find((f) => f.facilityId === facility)?.name ?? "facility");
  }
  if (header === "needs") parts.push("Needs you");
  if (header === "arrived") parts.push("Arrived since last visit");
  if (header === "blocked") parts.push("Blocked");
  return parts.join(" + ") || "this filter";
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

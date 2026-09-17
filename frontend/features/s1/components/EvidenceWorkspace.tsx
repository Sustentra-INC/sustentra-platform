"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import { createAuditIntent, type AuditIntentAction, type SessionAuditEntry } from "../utils/auditIntent";
import type {
  Ask,
  ContainerState,
  EngagementConfig,
  EvidenceItem,
  NoteEntry,
  RequestType,
} from "../types";
import { StateIndicator } from "./StateIndicator";
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

/** Canonical type vocabulary (grouping order). "Type unresolved" sits first. */
const TYPE_ORDER: string[] = [
  "Type unresolved",
  "Electricity bill",
  "Natural gas bill",
  "Other fuel invoice",
  "Fleet fuel statement",
  "Refrigerant service log or refrigerant purchase invoice",
  "Meter reading or meter photo",
  "Energy management system export",
  "Inventory workbook",
  "Facility list",
  "Organizational boundary statement",
  "Emission factor source list",
  "Renewable energy certificate or retirement statement",
  "Power purchase agreement or supplier contract",
  "Supplier-specific factor documentation",
  "Prior-year inventory or report",
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
  onOpenExtraction: (documentId: string) => void;
  onOpenRequests?: () => void;
  onOpenSetup?: () => void;
  onUploadFiles?: (files: FileList) => void;
  isUploading?: boolean;
  writesEnabled?: boolean;
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
  onOpenExtraction,
  onOpenRequests,
  onOpenSetup,
  onUploadFiles,
  isUploading = false,
  writesEnabled = true,
  backendError,
  demoState,
  auditIntents = [],
  onAuditIntent,
}: EvidenceWorkspaceProps) {
  const [items, setItems] = useState<EvidenceItem[]>(evidence);
  const [facilityFilter, setFacilityFilter] = useState<FacilityFilter>(null);
  const [headerFilter, setHeaderFilter] = useState<HeaderFilter>(null);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<string[]>([]);
  const [editing, setEditing] = useState<{ id: string; field: "type" | "facility" } | null>(null);
  const [noteFor, setNoteFor] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [modalDoc, setModalDoc] = useState<EvidenceItem | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | null>(null);

  useEffect(() => setItems(evidence), [evidence]);

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
    setItems((cur) =>
      cur.map((i) =>
        i.documentId === documentId
          ? { ...i, detectedType: nextType, typeReviewBand: null, typeReviewReason: null }
          : i
      )
    );
    setEditing(null);
    record("set_type", documentId, prev, nextType);
    flash(`Type set to ${nextType}`);
  }

  function setFacility(documentId: string, facilityId: string) {
    const facility = engagement.facilities.find((f) => f.facilityId === facilityId);
    if (!facility) return;
    setItems((cur) =>
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
    const entry: NoteEntry = {
      id: `n-${documentId}-${Date.now()}`,
      author: raisedByDefault(engagement).name,
      at: new Date().toISOString(),
      text,
    };
    setItems((cur) =>
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
    const others = items.filter((i) => i.documentId !== documentId && i.disposition === "active");
    const label = window.prompt(
      `Mark this file as ${kind === "duplicate" ? "a duplicate of" : "superseding"} which file?\nType part of the file name.`,
      ""
    );
    if (!label) return;
    const target = others.find((i) => i.filename.toLowerCase().includes(label.toLowerCase()));
    if (!target) {
      flash(`No file matched "${label}"`);
      return;
    }
    setItems((cur) =>
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
    setItems((cur) => cur.map((i) => (i.documentId === documentId ? { ...i, disposition: "withdrawn" } : i)));
    record("withdraw_document", documentId, "active", "withdrawn");
    flash(`Withdrew ${item.filename}`);
  }

  function reinstate(documentId: string) {
    setItems((cur) => cur.map((i) => (i.documentId === documentId ? { ...i, disposition: "active" } : i)));
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
    <section className="s1-content s1-ws">
      <WorkspaceHeader
        engagement={engagement}
        counts={headerCounts}
        activeFilter={headerFilter}
        onFilter={(f) => setHeaderFilter((cur) => (cur === f ? null : f))}
        onOpenSetup={() => (onOpenSetup ? onOpenSetup() : flash("Setup is not built yet."))}
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
            <div className="s1-table-wrap">
              <table className="s1-table s1-ws-table">
                <colgroup>
                  <col style={{ minWidth: 210 }} />
                  <col style={{ width: 150 }} />
                  <col style={{ width: 170 }} />
                  <col style={{ width: 150 }} />
                  <col style={{ width: 190 }} />
                  <col style={{ width: 150 }} />
                  <col style={{ width: 160 }} />
                  <col style={{ width: 40 }} />
                </colgroup>
                <thead>
                  <tr>
                    <th>Document</th>
                    <th>Facility</th>
                    <th>Document type</th>
                    <th>Processing state</th>
                    <th>Issue</th>
                    <th>Add to requests</th>
                    <th title="Notes are not evidence.">Notes</th>
                    <th aria-label="Row menu"></th>
                  </tr>
                </thead>
                <tbody>
                  {groups.map((group) => (
                    <Fragment key={group.type}>
                      <tr className="s1-ws-group">
                        <td colSpan={8}>
                          {group.type} <span className="s1-muted">({group.items.length})</span>
                        </td>
                      </tr>
                      {group.items.map((item) => (
                        <Fragment key={item.documentId}>
                          <WorkspaceRow
                            item={item}
                            items={items}
                            asks={asks}
                            engagement={engagement}
                            writesEnabled={writesEnabled}
                            editing={editing?.id === item.documentId ? editing.field : null}
                            menuOpen={openMenuId === item.documentId}
                            expanded={expandedIds.includes(item.documentId)}
                            noteOpen={noteFor === item.documentId}
                            noteDraft={noteDraft}
                            onNoteDraft={setNoteDraft}
                            onOpenExtraction={onOpenExtraction}
                            onOpenRequests={() => (onOpenRequests ? onOpenRequests() : flash("Evidence requests is built next."))}
                            onStartEdit={(field) => setEditing({ id: item.documentId, field })}
                            onCancelEdit={() => setEditing(null)}
                            onSetType={setType}
                            onSetFacility={setFacility}
                            onStartNote={() => {
                              setNoteFor(item.documentId);
                              setNoteDraft("");
                            }}
                            onSaveNote={() => addNote(item.documentId)}
                            onCancelNote={() => setNoteFor(null)}
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
                          {expandedIds.includes(item.documentId) ? (
                            <tr className="s1-history-row">
                              <td colSpan={8}>
                                <RowRecord item={item} intents={auditIntents.filter((a) => a.documentId === item.documentId)} />
                              </td>
                            </tr>
                          ) : null}
                        </Fragment>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
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
  engagement,
  counts,
  activeFilter,
  onFilter,
  onOpenSetup,
}: {
  engagement: EngagementConfig;
  counts: { needs: number; arrived: number; blocked: number };
  activeFilter: HeaderFilter;
  onFilter: (f: HeaderFilter) => void;
  onOpenSetup: () => void;
}) {
  return (
    <header className="s1-ws-header">
      <div className="s1-ws-header__id">
        <h1>{engagement.clientName}</h1>
        <button className="s1-linklike" type="button" onClick={onOpenSetup}>
          Setup
        </button>
        <span className="s1-muted">Since your last visit: {counts.arrived} new</span>
      </div>
      <div className="s1-ws-header__counts">
        <CountFilter label="Needs you" n={counts.needs} on={activeFilter === "needs"} onClick={() => onFilter("needs")} />
        <CountFilter
          label="Arrived since last visit"
          n={counts.arrived}
          on={activeFilter === "arrived"}
          onClick={() => onFilter("arrived")}
        />
        <CountFilter label="Blocked" n={counts.blocked} on={activeFilter === "blocked"} onClick={() => onFilter("blocked")} />
      </div>
    </header>
  );
}

function CountFilter({ label, n, on, onClick }: { label: string; n: number; on: boolean; onClick: () => void }) {
  return (
    <button className={`s1-ws-count${on ? " is-on" : ""}`} type="button" aria-pressed={on} onClick={onClick}>
      <span className="s1-ws-count__n">{n}</span> {label}
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
  editing: "type" | "facility" | null;
  menuOpen: boolean;
  expanded: boolean;
  noteOpen: boolean;
  noteDraft: string;
  onNoteDraft: (v: string) => void;
  onOpenExtraction: (id: string) => void;
  onOpenRequests: () => void;
  onStartEdit: (field: "type" | "facility") => void;
  onCancelEdit: () => void;
  onSetType: (id: string, type: string) => void;
  onSetFacility: (id: string, facilityId: string) => void;
  onStartNote: () => void;
  onSaveNote: () => void;
  onCancelNote: () => void;
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
  const issues = issueLines(item, items, engagement);
  const ask = latestAsk(asks, item.documentId);
  const askCount = asks.filter((a) => a.source.documentId === item.documentId).length;

  return (
    <tr className={withdrawn ? "s1-row-withdrawn" : ""}>
      {/* Document */}
      <td>
        <button className="s1-doc-link" type="button" onClick={() => props.onOpenExtraction(item.documentId)}>
          {item.filename}
        </button>
        <div className="s1-mono s1-muted">
          {item.answeredRequestNumber != null
            ? `Answered request ${item.answeredRequestNumber} · ${formatDate(item.uploadedAt)}`
            : `Uploaded · ${formatDate(item.uploadedAt)}`}
        </div>
        {withdrawn ? <StateIndicator dimension="disposition" value="withdrawn" label="Withdrawn" /> : null}
      </td>

      {/* Facility */}
      <td>
        {props.editing === "facility" ? (
          <select
            className="s1-inline-input"
            defaultValue=""
            onChange={(e) => props.onSetFacility(item.documentId, e.target.value)}
          >
            <option value="" disabled>
              Set facility
            </option>
            {engagement.facilities.map((f) => (
              <option key={f.facilityId} value={f.facilityId}>
                {f.name}
              </option>
            ))}
          </select>
        ) : (
          <FacilityCell item={item} onSet={() => props.onStartEdit("facility")} writesEnabled={props.writesEnabled} />
        )}
      </td>

      {/* Document type */}
      <td>
        {props.editing === "type" ? (
          <select
            className="s1-inline-input"
            defaultValue={item.detectedType ?? ""}
            onChange={(e) => props.onSetType(item.documentId, e.target.value)}
          >
            <option value="" disabled>
              Set type
            </option>
            {SET_TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        ) : (
          <TypeCell item={item} onSet={() => props.onStartEdit("type")} writesEnabled={props.writesEnabled} />
        )}
      </td>

      {/* Processing state */}
      <td>
        <span className={`s1-state s1-state--${proc.role}`}>{proc.label}</span>
        {proc.sub ? <div className="s1-reason">{proc.sub}</div> : null}
      </td>

      {/* Issue */}
      <td>
        {issues.length === 0 ? (
          <span className="s1-muted">—</span>
        ) : (
          <div className="s1-ws-issues">
            {issues.map((line) => (
              <div key={line}>{line}</div>
            ))}
          </div>
        )}
      </td>

      {/* Add to requests */}
      <td>
        <AddToRequestsCell
          ask={ask}
          count={askCount}
          withdrawn={withdrawn}
          onAdd={props.onAddToRequests}
          onOpenRequests={props.onOpenRequests}
        />
      </td>

      {/* Notes */}
      <td>
        <NotesCell
          item={item}
          open={props.noteOpen}
          draft={props.noteDraft}
          onDraft={props.onNoteDraft}
          onStart={props.onStartNote}
          onSave={props.onSaveNote}
          onCancel={props.onCancelNote}
        />
      </td>

      {/* Menu */}
      <td>
        <RowMenu
          item={item}
          isOpen={props.menuOpen}
          onOpenChange={props.onMenu}
          onOpen={() => props.onOpenExtraction(item.documentId)}
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

function FacilityCell({ item, onSet, writesEnabled }: { item: EvidenceItem; onSet: () => void; writesEnabled: boolean }) {
  if (item.facilityState === "resolved") {
    return (
      <div>
        <div>{item.facilityName}</div>
        <div className="s1-muted s1-ws-src">from accepted value</div>
      </div>
    );
  }
  if (item.facilityState === "multiple") {
    return (
      <div>
        <div>Multiple facilities</div>
        <div className="s1-muted s1-ws-src">{item.facilityCount ?? 2} facilities</div>
      </div>
    );
  }
  if (item.facilityState === "not_facility_scoped") {
    return (
      <div>
        <div>No facility</div>
        <div className="s1-muted s1-ws-src">entity-level</div>
      </div>
    );
  }
  return (
    <div>
      <div className="s1-muted">Not yet known</div>
      {writesEnabled ? (
        <button className="s1-linklike" type="button" onClick={onSet}>
          Set facility
        </button>
      ) : null}
    </div>
  );
}

function TypeCell({ item, onSet, writesEnabled }: { item: EvidenceItem; onSet: () => void; writesEnabled: boolean }) {
  const unconfirmed = item.detectedType == null || item.typeReviewBand === "needs_review" || item.typeReviewBand === "cannot_determine";
  return (
    <div>
      <div>{item.detectedType ?? <span className="s1-muted">Type unresolved</span>}</div>
      {unconfirmed ? <div className="s1-muted s1-ws-src">unconfirmed</div> : null}
      {writesEnabled ? (
        <button className="s1-linklike" type="button" onClick={onSet}>
          Set type
        </button>
      ) : null}
    </div>
  );
}

function AddToRequestsCell({
  ask,
  count,
  withdrawn,
  onAdd,
  onOpenRequests,
}: {
  ask: Ask | null;
  count: number;
  withdrawn: boolean;
  onAdd: () => void;
  onOpenRequests: () => void;
}) {
  if (!ask) {
    if (withdrawn) return <span className="s1-muted">—</span>;
    return (
      <button className="s1-linklike" type="button" onClick={onAdd}>
        Add to requests
      </button>
    );
  }
  const label =
    ask.state === "not_yet_sent"
      ? "In requests · not yet sent"
      : ask.state === "requested"
        ? `Requested · request ${ask.requestNumber}`
        : ask.state === "resolved"
          ? "Resolved"
          : "Withdrawn";
  return (
    <div>
      <button className="s1-linklike" type="button" onClick={onOpenRequests}>
        {label}
      </button>
      {count > 1 ? <div className="s1-muted s1-ws-src">{count} asks</div> : null}
    </div>
  );
}

function NotesCell({
  item,
  open,
  draft,
  onDraft,
  onStart,
  onSave,
  onCancel,
}: {
  item: EvidenceItem;
  open: boolean;
  draft: string;
  onDraft: (v: string) => void;
  onStart: () => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const notes = item.notes ?? [];
  const latest = notes[notes.length - 1];
  if (open) {
    return (
      <div className="s1-ws-note-edit">
        <input
          className="s1-inline-input"
          value={draft}
          autoFocus
          placeholder="Add a note"
          onChange={(e) => onDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onSave();
            if (e.key === "Escape") onCancel();
          }}
        />
        <button className="s1-button s1-button--compact" type="button" onClick={onSave}>
          Save
        </button>
      </div>
    );
  }
  return (
    <div className="s1-ws-notes">
      {latest ? (
        <>
          <div className="s1-ws-note-line">{latest.text}</div>
          <div className="s1-mono s1-muted">
            {latest.author} · {formatDate(latest.at)}
          </div>
        </>
      ) : (
        <span className="s1-muted">—</span>
      )}
      <button className="s1-linklike" type="button" aria-label="Add note" onClick={onStart}>
        + note
      </button>
    </div>
  );
}

function RowMenu({
  item,
  isOpen,
  onOpenChange,
  onOpen,
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
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onOpen: () => void;
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
        { label: "Open", action: onOpen },
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
      {isOpen ? (
        <div className="s1-menu__panel" role="menu" ref={menuRef}>
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
        </div>
      ) : null}
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
        <strong>Activity</strong>
        {intents.length === 0 ? (
          <div className="s1-muted">No recorded activity for this row in this session.</div>
        ) : (
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
    const type = item.detectedType ?? "Type unresolved";
    map.set(type, [...(map.get(type) ?? []), item]);
  }
  const order = (t: string) => {
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

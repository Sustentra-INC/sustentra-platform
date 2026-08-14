"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";

import { EXACT_COPY } from "../constants/copy";
import { useKeyboardNavigation } from "../hooks/useKeyboardNavigation";
import { activeEvidenceItems, selectableEvidenceIds, workspaceNeeds } from "../utils/workspaceState";
import type { SessionAuditEntry } from "../utils/auditIntent";
import { createAuditIntent } from "../utils/auditIntent";
import type {
  ContainerState,
  EngagementConfig,
  EvidenceItem,
  FacilityState,
  PeriodState,
  ProcessingState,
  RelationshipKind,
} from "../types";
import { ContainerStateSurface } from "./ContainerStateSurface";
import { StateIndicator } from "./StateIndicator";

export type GroupBy = "none" | "facility" | "period" | "type";

interface EvidenceWorkspaceProps {
  engagement: EngagementConfig;
  evidence: EvidenceItem[];
  supportive: EvidenceItem[];
  auditIntents: SessionAuditEntry[];
  demoState: ContainerState;
  workspaceState: EvidenceWorkspaceState;
  onAuditIntent: (intent: SessionAuditEntry) => void;
  onDemoState: (state: ContainerState) => void;
  onWorkspaceState: (state: EvidenceWorkspaceState) => void;
  onOpenExtraction: (documentId: string, scrollTop: number) => void;
  onOpenManualEntry: (documentId: string, scrollTop: number) => void;
  onUploadFiles?: (files: FileList) => void;
  onProcessDocument?: (documentId: string) => void;
  isUploading?: boolean;
  processingDocumentIds?: string[];
  backendError?: string | null;
  workspaceWritesEnabled?: boolean;
  showSessionAuditIntents?: boolean;
}

export interface Filters {
  processingState: "all" | ProcessingState;
  typeBand: "all" | "auto_accepted" | "needs_review" | "cannot_determine";
  facilityState: "all" | FacilityState;
  periodState: "all" | PeriodState;
  flags: "all" | RelationshipKind;
}

export interface EvidenceWorkspaceState {
  filters: Filters;
  groupBy: GroupBy;
  selectedIds: string[];
  scrollTop: number;
}

export const defaultFilters: Filters = {
  processingState: "all",
  typeBand: "all",
  facilityState: "all",
  periodState: "all",
  flags: "all",
};

export const defaultWorkspaceState: EvidenceWorkspaceState = {
  filters: defaultFilters,
  groupBy: "none",
  selectedIds: [],
  scrollTop: 0,
};

const BACKEND_DISABLED_REASON = "No save endpoint yet -- see revision section 3.";

export function EvidenceWorkspace({
  engagement,
  evidence,
  supportive,
  auditIntents,
  demoState,
  workspaceState,
  onAuditIntent,
  onDemoState,
  onWorkspaceState,
  onOpenExtraction,
  onOpenManualEntry,
  onUploadFiles,
  onProcessDocument,
  isUploading = false,
  processingDocumentIds = [],
  backendError,
  workspaceWritesEnabled = true,
  showSessionAuditIntents = true,
}: EvidenceWorkspaceProps) {
  const [items, setItems] = useState(evidence);
  const { filters, groupBy, selectedIds } = workspaceState;
  const [editingFacilityId, setEditingFacilityId] = useState<string | null>(null);
  const [editingPeriodId, setEditingPeriodId] = useState<string | null>(null);
  const [periodDraft, setPeriodDraft] = useState({ start: "", end: "" });
  const [editingTypeId, setEditingTypeId] = useState<string | null>(null);
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(evidence[0]?.documentId ?? null);
  const [uploadFailures, setUploadFailures] = useState<Array<{ filename: string; reason: string }>>([]);
  const [workingActionIds, setWorkingActionIds] = useState<string[]>([]);
  const [expandedHistoryIds, setExpandedHistoryIds] = useState<string[]>([]);

  useEffect(() => {
    setItems(evidence);
    setActiveDocumentId((current) => current ?? evidence[0]?.documentId ?? null);
  }, [evidence]);

  const activeItems = useMemo(() => activeEvidenceItems(items), [items]);
  const needs = useMemo(() => workspaceNeeds(items), [items]);

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      if (filters.processingState !== "all" && item.processingState !== filters.processingState) {
        return false;
      }
      if (filters.typeBand !== "all" && item.typeReviewBand !== filters.typeBand) {
        return false;
      }
      if (filters.facilityState !== "all" && item.facilityState !== filters.facilityState) {
        return false;
      }
      if (filters.periodState !== "all" && item.periodState !== filters.periodState) {
        return false;
      }
      if (
        filters.flags !== "all" &&
        !item.relationships.some((relationship) => relationship.kind === filters.flags)
      ) {
        return false;
      }
      return true;
    });
  }, [filters, items]);

  const groupedItems = useMemo(() => groupItems(filteredItems, groupBy), [filteredItems, groupBy]);
  const allFilteredSelected =
    filteredItems.length > 0 && filteredItems.every((item) => selectedIds.includes(item.documentId));

  function updateFilter<Key extends keyof Filters>(key: Key, value: Filters[Key]) {
    onWorkspaceState({
      ...workspaceState,
      filters: { ...filters, [key]: value },
      selectedIds: [],
    });
  }

  function updateGroup(nextGroup: GroupBy) {
    onWorkspaceState({ ...workspaceState, groupBy: nextGroup, selectedIds: [] });
  }

  function clearFilters() {
    onWorkspaceState({ ...workspaceState, filters: defaultFilters, selectedIds: [] });
  }

  function toggleRow(documentId: string) {
    const item = items.find((candidate) => candidate.documentId === documentId);
    if (item?.disposition === "withdrawn") return;
    onWorkspaceState(
      {
        ...workspaceState,
        selectedIds: selectedIds.includes(documentId)
          ? selectedIds.filter((id) => id !== documentId)
          : [...selectedIds, documentId],
      }
    );
  }

  function toggleFiltered() {
    onWorkspaceState({
      ...workspaceState,
      selectedIds: allFilteredSelected ? [] : selectableEvidenceIds(filteredItems),
    });
  }

  function assignFacility(documentId: string, facilityId: string) {
    const facility = engagement.facilities.find((option) => option.facilityId === facilityId);
    if (!facility) return;
    setItems((current) =>
      current.map((item) =>
        item.documentId === documentId
          ? {
              ...item,
              facilityState: "resolved",
              facilityId: facility.facilityId,
              facilityName: facility.name,
            }
          : item
      )
    );
    setEditingFacilityId(null);
    onAuditIntent(
      createAuditIntent({
        action: "assign_facility",
        documentId,
        oldValue: null,
        newValue: facility.name,
      })
    );
  }

  function runWriteAction(actionId: string, action: () => void) {
    if (workingActionIds.includes(actionId)) return;
    setWorkingActionIds((current) => [...current, actionId]);
    window.setTimeout(() => {
      action();
      setWorkingActionIds((current) => current.filter((id) => id !== actionId));
    }, 120);
  }

  function assignPeriod(documentId: string) {
    if (!periodDraft.start || !periodDraft.end) return;
    setItems((current) =>
      current.map((item) =>
        item.documentId === documentId
          ? {
              ...item,
              periodState: "resolved",
              periodStart: periodDraft.start,
              periodEnd: periodDraft.end,
            }
          : item
      )
    );
    setEditingPeriodId(null);
    onAuditIntent(
      createAuditIntent({
        action: "assign_period",
        documentId,
        oldValue: null,
        newValue: `${periodDraft.start} to ${periodDraft.end}`,
      })
    );
  }

  function acceptType(documentId: string) {
    const item = items.find((candidate) => candidate.documentId === documentId);
    setItems((current) =>
      current.map((candidate) =>
        candidate.documentId === documentId
          ? { ...candidate, typeReviewBand: null, typeReviewReason: null }
          : candidate
      )
    );
    onAuditIntent(
      createAuditIntent({
        action: "accept_detected_type",
        documentId,
        oldValue: item?.typeReviewBand ?? null,
        newValue: item?.detectedType ?? null,
      })
    );
  }

  function changeType(documentId: string, nextType: string) {
    const item = items.find((candidate) => candidate.documentId === documentId);
    setItems((current) =>
      current.map((candidate) =>
        candidate.documentId === documentId
          ? {
              ...candidate,
              detectedType: nextType,
              typeReviewBand: "auto_accepted",
              typeReviewReason: null,
            }
          : candidate
      )
    );
    setEditingTypeId(null);
    onAuditIntent(
      createAuditIntent({
        action: "change_type",
        documentId,
        oldValue: item?.detectedType ?? null,
        newValue: nextType,
      })
    );
  }

  function withdrawDocument(documentId: string) {
    const item = items.find((candidate) => candidate.documentId === documentId);
    if (!item) return;
    const ok = window.confirm(`Withdraw ${item.filename}?`);
    if (!ok) return;
    setItems((current) =>
      current.map((candidate) =>
        candidate.documentId === documentId ? { ...candidate, disposition: "withdrawn" } : candidate
      )
    );
    onWorkspaceState({
      ...workspaceState,
      selectedIds: selectedIds.filter((id) => id !== documentId),
    });
    onAuditIntent(
      createAuditIntent({
        action: "withdraw_document",
        documentId,
        oldValue: "active",
        newValue: "withdrawn",
      })
    );
  }

  function reinstateDocument(documentId: string) {
    setItems((current) =>
      current.map((candidate) =>
        candidate.documentId === documentId ? { ...candidate, disposition: "active" } : candidate
      )
    );
    onAuditIntent(
      createAuditIntent({
        action: "reinstate_document",
        documentId,
        oldValue: "withdrawn",
        newValue: "active",
      })
    );
  }

  function bulkAcceptType() {
    const targets = items.filter(
      (item) => selectedIds.includes(item.documentId) && item.typeReviewBand && item.detectedType
    );
    if (targets.length === 0) return;
    const ok = window.confirm(`Accept detected type for ${targets.length} documents?`);
    if (!ok) return;
    targets.forEach((item) => acceptType(item.documentId));
    onWorkspaceState({ ...workspaceState, selectedIds: [] });
  }

  const hasFilter = Object.values(filters).some((value) => value !== "all");
  const tableState =
    demoState === "populated" && filteredItems.length === 0 ? "empty_filtered" : demoState;

  return (
    <>
      {demoState !== "empty_nothing_yet" ? (
        <NeedsYouBar needs={needs} hasFilter={hasFilter} onFilter={updateFilter} />
      ) : null}
      <section className="s1-content">
        {showSessionAuditIntents ? <DemoControls state={demoState} onState={onDemoState} /> : null}
        {backendError ? <SystemDegradedBanner message={backendError} /> : null}
        {tableState !== "populated" ? (
          <ContainerStateSurface
            state={tableState}
            totalDocuments={items.length}
            onClearFilter={clearFilters}
            onUploadFiles={onUploadFiles}
            isUploading={isUploading}
          />
        ) : (
          <>
            <UploadArea
              onUploadFiles={onUploadFiles}
              isUploading={isUploading}
              uploadFailures={uploadFailures}
              onUploadFailure={(failure) => setUploadFailures((current) => [failure, ...current].slice(0, 5))}
              onUploadStart={() => setUploadFailures([])}
            />
            <TypeReviewStrip
              items={items}
              onSetFilter={(band) => updateFilter("typeBand", band)}
            />
            <EvidenceToolbar
              filters={filters}
              groupBy={groupBy}
              onFilter={updateFilter}
              onGroup={updateGroup}
              onClear={clearFilters}
            />
            {selectedIds.length > 0 ? (
              <BulkActionBar
                count={selectedIds.length}
                disabled={!workspaceWritesEnabled}
                onAcceptType={bulkAcceptType}
              />
            ) : null}
            <ContainerStateSurface
              state="populated"
              totalDocuments={items.length}
              onClearFilter={clearFilters}
            >
            <EvidenceTable
              groups={groupedItems}
              flatItems={filteredItems}
              selectedIds={selectedIds}
              activeDocumentId={activeDocumentId}
              allFilteredSelected={allFilteredSelected}
              onToggleFiltered={toggleFiltered}
              onToggleRow={toggleRow}
              onActiveRow={setActiveDocumentId}
              onOpenExtraction={(documentId) =>
                onOpenExtraction(documentId, typeof window === "undefined" ? 0 : window.scrollY)
              }
              onOpenManualEntry={(documentId) =>
                onOpenManualEntry(documentId, typeof window === "undefined" ? 0 : window.scrollY)
              }
              onProcessDocument={onProcessDocument}
              processingDocumentIds={processingDocumentIds}
                editingFacilityId={editingFacilityId}
                editingPeriodId={editingPeriodId}
                editingTypeId={editingTypeId}
                periodDraft={periodDraft}
                engagement={engagement}
                workspaceWritesEnabled={workspaceWritesEnabled}
                onStartFacility={setEditingFacilityId}
                workingActionIds={workingActionIds}
                onAssignFacility={(documentId, facilityId) =>
                  runWriteAction(`facility:${documentId}`, () => assignFacility(documentId, facilityId))
                }
                onStartPeriod={(documentId) => {
                  setEditingPeriodId(documentId);
                  setPeriodDraft({ start: "", end: "" });
                }}
                onPeriodDraft={setPeriodDraft}
                onAssignPeriod={(documentId) => runWriteAction(`period:${documentId}`, () => assignPeriod(documentId))}
              onAcceptType={(documentId) => runWriteAction(`type:${documentId}`, () => acceptType(documentId))}
              onStartType={setEditingTypeId}
              onChangeType={(documentId, nextType) =>
                runWriteAction(`type:${documentId}`, () => changeType(documentId, nextType))
              }
              onWithdraw={(documentId) =>
                runWriteAction(`withdraw:${documentId}`, () => withdrawDocument(documentId))
              }
              onReinstate={(documentId) =>
                runWriteAction(`withdraw:${documentId}`, () => reinstateDocument(documentId))
              }
              expandedHistoryIds={expandedHistoryIds}
              auditIntents={auditIntents}
              onToggleHistory={(documentId) =>
                setExpandedHistoryIds((current) =>
                  current.includes(documentId)
                    ? current.filter((id) => id !== documentId)
                    : [...current, documentId]
                )
              }
              onCancelInlineEdit={() => {
                setEditingFacilityId(null);
                setEditingPeriodId(null);
                setEditingTypeId(null);
              }}
            />
            </ContainerStateSurface>
            <SupportiveEvidenceCards items={supportive} />
            <CompletenessPanel />
            {showSessionAuditIntents ? (
              <>
                <NonRetentionNotice />
                <ActivityRegion intents={auditIntents} />
              </>
            ) : null}
          </>
        )}
      </section>
    </>
  );
}

function DemoControls({
  state,
  onState,
}: {
  state: ContainerState;
  onState: (state: ContainerState) => void;
}) {
  const options: Array<{ value: ContainerState; label: string }> = [
    { value: "populated", label: "populated" },
    { value: "empty_nothing_yet", label: "empty nothing yet" },
    { value: "empty_filtered", label: "filtered empty" },
    { value: "loading", label: "loading" },
    { value: "error_degraded", label: "degraded" },
    { value: "dependency_blocked", label: "dependency blocked" },
  ];

  return (
    <div className="s1-demo-controls" aria-label="S1 demo controls">
      <strong>S1 demo controls</strong>
      <label>
        State{" "}
        <select value={state} onChange={(event) => onState(event.target.value as ContainerState)}>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

function NeedsYouBar({
  needs,
  hasFilter,
  onFilter,
}: {
  needs: { type: number; unacceptedTypes: number; facility: number; period: number; blocked: number };
  hasFilter: boolean;
  onFilter: <Key extends keyof Filters>(key: Key, value: Filters[Key]) => void;
}) {
  return (
    <div className="s1-needs">
      <strong>Needs you</strong>
      <button className="s1-needs__item" type="button" onClick={() => onFilter("typeBand", "needs_review")}>
        {needs.type} type review
      </button>
      <button className="s1-needs__item" type="button" onClick={() => onFilter("typeBand", "auto_accepted")}>
        {needs.unacceptedTypes} unaccepted types
      </button>
      <button className="s1-needs__item" type="button" onClick={() => onFilter("facilityState", "unresolved")}>
        {needs.facility} facility
      </button>
      <button className="s1-needs__item" type="button" onClick={() => onFilter("periodState", "unresolved")}>
        {needs.period} period
      </button>
      <button className="s1-needs__item" type="button" onClick={() => onFilter("processingState", "blocked")}>
        {needs.blocked} blocked
      </button>
      {hasFilter ? <span className="s1-needs__note">{EXACT_COPY.filterActive}</span> : null}
    </div>
  );
}

function SystemDegradedBanner({ message }: { message: string }) {
  return (
    <div className="s1-system-banner" role="status">
      <strong>Backend call failed</strong>
      <span>{message}</span>
      <span>Local filters and review navigation remain available.</span>
    </div>
  );
}

function UploadArea({
  onUploadFiles,
  isUploading,
  uploadFailures = [],
  onUploadFailure,
  onUploadStart,
}: {
  onUploadFiles?: (files: FileList) => void;
  isUploading: boolean;
  uploadFailures?: Array<{ filename: string; reason: string }>;
  onUploadFailure?: (failure: { filename: string; reason: string }) => void;
  onUploadStart?: () => void;
}) {
  const [isDragOver, setIsDragOver] = useState(false);

  function submitFiles(files: FileList) {
    if (files.length === 0) return;
    onUploadStart?.();
    if (!onUploadFiles) {
      Array.from(files).forEach((file) =>
        onUploadFailure?.({ filename: file.name, reason: BACKEND_DISABLED_REASON })
      );
      return;
    }
    onUploadFiles(files);
  }

  return (
    <div
      className={`s1-band s1-upload ${isDragOver ? "s1-upload--drag" : ""} ${isUploading ? "s1-upload--busy" : ""}`}
      onDragEnter={(event) => {
        event.preventDefault();
        setIsDragOver(true);
      }}
      onDragOver={(event) => {
        event.preventDefault();
        setIsDragOver(true);
      }}
      onDragLeave={(event) => {
        if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
        setIsDragOver(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragOver(false);
        if (event.dataTransfer.files.length > 0) {
          submitFiles(event.dataTransfer.files);
        }
      }}
    >
      <div>
        <h3>Upload evidence</h3>
        <div className="s1-muted">Drop files here or choose files</div>
        {uploadFailures.length > 0 ? (
          <div className="s1-upload__failures" role="status">
            {uploadFailures.map((failure) => (
              <div key={`${failure.filename}-${failure.reason}`}>
                {failure.filename}: {failure.reason}
              </div>
            ))}
          </div>
        ) : null}
      </div>
      <label className="s1-button">
        {isUploading ? "Uploading" : "Choose files"}
        <input
          className="s1-file-input"
          type="file"
          multiple
          onChange={(event) => {
            if (event.target.files && event.target.files.length > 0) {
              submitFiles(event.target.files);
              event.target.value = "";
            }
          }}
        />
      </label>
    </div>
  );
}

function TypeReviewStrip({
  items,
  onSetFilter,
}: {
  items: EvidenceItem[];
  onSetFilter: (band: "needs_review" | "cannot_determine") => void;
}) {
  const needsReview = items.filter((item) => item.typeReviewBand === "needs_review").length;
  const cannotDetermine = items.filter((item) => item.typeReviewBand === "cannot_determine").length;
  if (needsReview + cannotDetermine === 0) return null;

  return (
    <div className="s1-band">
      <strong>Type review</strong>{" "}
      <button className="s1-needs__item" type="button" onClick={() => onSetFilter("needs_review")}>
        {needsReview} needs review
      </button>
      <button className="s1-needs__item" type="button" onClick={() => onSetFilter("cannot_determine")}>
        {cannotDetermine} cannot determine
      </button>
    </div>
  );
}

function EvidenceToolbar({
  filters,
  groupBy,
  onFilter,
  onGroup,
  onClear,
}: {
  filters: Filters;
  groupBy: GroupBy;
  onFilter: <Key extends keyof Filters>(key: Key, value: Filters[Key]) => void;
  onGroup: (groupBy: GroupBy) => void;
  onClear: () => void;
}) {
  return (
    <div className="s1-toolbar">
      <label>
        Group by{" "}
        <select value={groupBy} onChange={(event) => onGroup(event.target.value as GroupBy)}>
          <option value="none">None</option>
          <option value="facility">Facility</option>
          <option value="period">Period</option>
          <option value="type">Type</option>
        </select>
      </label>
      <label>
        Processing{" "}
        <select
          value={filters.processingState}
          onChange={(event) => onFilter("processingState", event.target.value as Filters["processingState"])}
        >
          <option value="all">All</option>
          <option value="not_ingested">Not ingested</option>
          <option value="ingested">Ingested</option>
          <option value="typed">Typed</option>
          <option value="extracted">Extracted</option>
          <option value="blocked">Blocked</option>
        </select>
      </label>
      <label>
        Band{" "}
        <select
          value={filters.typeBand}
          onChange={(event) => onFilter("typeBand", event.target.value as Filters["typeBand"])}
        >
          <option value="all">All</option>
          <option value="auto_accepted">auto-accepted</option>
          <option value="needs_review">needs review</option>
          <option value="cannot_determine">cannot determine</option>
        </select>
      </label>
      <label>
        Facility{" "}
        <select
          value={filters.facilityState}
          onChange={(event) => onFilter("facilityState", event.target.value as Filters["facilityState"])}
        >
          <option value="all">All</option>
          <option value="resolved">resolved</option>
          <option value="unresolved">unresolved</option>
          <option value="multiple">multiple</option>
          <option value="not_facility_scoped">not facility-scoped</option>
        </select>
      </label>
      <label>
        Period{" "}
        <select
          value={filters.periodState}
          onChange={(event) => onFilter("periodState", event.target.value as Filters["periodState"])}
        >
          <option value="all">All</option>
          <option value="resolved">resolved</option>
          <option value="unresolved">unresolved</option>
          <option value="spans_multiple">spans multiple</option>
        </select>
      </label>
      <label>
        Flags{" "}
        <select value={filters.flags} onChange={(event) => onFilter("flags", event.target.value as Filters["flags"])}>
          <option value="all">All</option>
          <option value="duplicate">Duplicate</option>
          <option value="superseded_by">Superseded by</option>
          <option value="supersedes">Supersedes</option>
          <option value="conflicting_value">Conflicting value</option>
        </select>
      </label>
      <button className="s1-button" type="button" onClick={onClear}>
        Clear filter
      </button>
    </div>
  );
}

function BulkActionBar({
  count,
  disabled,
  onAcceptType,
}: {
  count: number;
  disabled: boolean;
  onAcceptType: () => void;
}) {
  return (
    <div className="s1-bulk">
      <strong>{count} selected</strong>
      <button
        className="s1-button"
        type="button"
        disabled={disabled}
        title={disabled ? BACKEND_DISABLED_REASON : undefined}
        onClick={onAcceptType}
      >
        Accept detected type
      </button>
      <button className="s1-button" type="button" disabled={disabled} title={disabled ? BACKEND_DISABLED_REASON : undefined}>
        Re-extract
      </button>
    </div>
  );
}

function EvidenceTable({
  groups,
  flatItems,
  selectedIds,
  activeDocumentId,
  allFilteredSelected,
  onToggleFiltered,
  onToggleRow,
  onActiveRow,
  onOpenExtraction,
  onOpenManualEntry,
  onProcessDocument,
  processingDocumentIds,
  workingActionIds,
  editingFacilityId,
  editingPeriodId,
  editingTypeId,
  periodDraft,
  engagement,
  workspaceWritesEnabled,
  onStartFacility,
  onAssignFacility,
  onStartPeriod,
  onPeriodDraft,
  onAssignPeriod,
  onAcceptType,
  onStartType,
  onChangeType,
  onWithdraw,
  onReinstate,
  expandedHistoryIds,
  auditIntents,
  onToggleHistory,
  onCancelInlineEdit,
}: {
  groups: Array<{ label: string | null; items: EvidenceItem[] }>;
  flatItems: EvidenceItem[];
  selectedIds: string[];
  activeDocumentId: string | null;
  allFilteredSelected: boolean;
  onToggleFiltered: () => void;
  onToggleRow: (documentId: string) => void;
  onActiveRow: (documentId: string) => void;
  onOpenExtraction: (documentId: string) => void;
  onOpenManualEntry: (documentId: string) => void;
  onProcess?: (documentId: string) => void;
  onProcessDocument?: (documentId: string) => void;
  processingDocumentIds: string[];
  workingActionIds: string[];
  editingFacilityId: string | null;
  editingPeriodId: string | null;
  editingTypeId: string | null;
  periodDraft: { start: string; end: string };
  engagement: EngagementConfig;
  workspaceWritesEnabled: boolean;
  onStartFacility: (documentId: string) => void;
  onAssignFacility: (documentId: string, facilityId: string) => void;
  onStartPeriod: (documentId: string) => void;
  onPeriodDraft: (draft: { start: string; end: string }) => void;
  onAssignPeriod: (documentId: string) => void;
  onAcceptType: (documentId: string) => void;
  onStartType: (documentId: string) => void;
  onChangeType: (documentId: string, type: string) => void;
  onWithdraw: (documentId: string) => void;
  onReinstate: (documentId: string) => void;
  expandedHistoryIds: string[];
  auditIntents: SessionAuditEntry[];
  onToggleHistory: (documentId: string) => void;
  onCancelInlineEdit: () => void;
}) {
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const activeIndex = Math.max(
    flatItems.findIndex((item) => item.documentId === activeDocumentId),
    0
  );
  const activeItem = flatItems[activeIndex];
  const handleRowKeys = useKeyboardNavigation({
    currentIndex: activeIndex,
    itemCount: flatItems.length,
    onMove: (nextIndex) => {
      const next = flatItems[nextIndex];
      if (next) onActiveRow(next.documentId);
    },
    onEnter: () => {
      if (activeItem) onOpenExtraction(activeItem.documentId);
    },
    onSpace: () => {
      if (activeItem) onToggleRow(activeItem.documentId);
    },
    onEscape: onCancelInlineEdit,
  });

  return (
    <div className="s1-table-wrap">
      <table className="s1-table">
        <colgroup>
          <col style={{ width: 32 }} />
          <col style={{ minWidth: 220 }} />
          <col style={{ width: 160 }} />
          <col style={{ width: 150 }} />
          <col style={{ width: 120 }} />
          <col style={{ width: 110 }} />
          <col style={{ width: 180 }} />
          <col style={{ width: 170 }} />
          <col style={{ width: 32 }} />
        </colgroup>
        <thead>
          <tr>
            <th>
              <input
                type="checkbox"
                checked={allFilteredSelected}
                onChange={onToggleFiltered}
                aria-label="Select filtered documents"
              />
            </th>
            <th>Document</th>
            <th>Detected type</th>
            <th>Facility</th>
            <th>Period</th>
            <th>Fields found / expected for type</th>
            <th>Processing state</th>
            <th>Flags</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group, index) => (
            <Fragment key={group.label ?? `ungrouped-${index}`}>
              {group.label ? (
                <tr key={`group-heading-${group.label}`}>
                  <td colSpan={9} className="s1-muted">
                    {group.label} ({group.items.length})
                  </td>
                </tr>
              ) : null}
              {group.items.map((item) => (
                <Fragment key={item.documentId}>
                <tr
                  className={[
                    selectedIds.includes(item.documentId) ? "s1-row-selected" : "",
                    activeDocumentId === item.documentId ? "s1-row-active" : "",
                    item.disposition === "withdrawn" ? "s1-row-withdrawn" : "",
                  ].filter(Boolean).join(" ")}
                  aria-current={activeDocumentId === item.documentId}
                  tabIndex={0}
                  onFocus={() => onActiveRow(item.documentId)}
                  onKeyDown={(event) => {
                    if (
                      event.target instanceof HTMLElement &&
                      ["INPUT", "SELECT", "BUTTON"].includes(event.target.tagName) &&
                      event.key !== "Escape"
                    ) {
                      return;
                    }
                    handleRowKeys(event);
                  }}
                >
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(item.documentId)}
                      onChange={() => onToggleRow(item.documentId)}
                      aria-label={`Select ${item.filename}`}
                    />
                  </td>
                  <td>
                    <button className="s1-doc-link" type="button" onClick={() => onOpenExtraction(item.documentId)}>
                      {item.filename}
                    </button>
                    <div className="s1-mono s1-muted">{item.documentId}</div>
                    {item.disposition === "withdrawn" ? (
                      <StateIndicator dimension="disposition" value="withdrawn" label="Withdrawn" />
                    ) : null}
                  </td>
                  <td>
                    <TypeCell
                      item={item}
                      editing={editingTypeId === item.documentId}
                      disabled={!workspaceWritesEnabled}
                      isWorking={workingActionIds.includes(`type:${item.documentId}`)}
                      onAcceptType={onAcceptType}
                      onStartType={onStartType}
                      onChangeType={onChangeType}
                    />
                  </td>
                  <td>
                    <FacilityCell
                      item={item}
                      editing={editingFacilityId === item.documentId}
                      facilities={engagement.facilities}
                      disabled={!workspaceWritesEnabled}
                      isWorking={workingActionIds.includes(`facility:${item.documentId}`)}
                      onStart={onStartFacility}
                      onAssign={onAssignFacility}
                    />
                  </td>
                  <td>
                    <PeriodCell
                      item={item}
                      editing={editingPeriodId === item.documentId}
                      draft={periodDraft}
                      disabled={!workspaceWritesEnabled}
                      isWorking={workingActionIds.includes(`period:${item.documentId}`)}
                      onStart={onStartPeriod}
                      onDraft={onPeriodDraft}
                      onAssign={onAssignPeriod}
                    />
                  </td>
                  <td className="s1-mono">
                    {item.fieldsExpectedDisplay === null ? "" : `${item.fieldsExtracted} of ${item.fieldsExpectedDisplay}`}
                  </td>
                  <td>
                    <ProcessingCell
                      item={item}
                      isProcessing={processingDocumentIds.includes(item.documentId)}
                      onProcess={onProcessDocument}
                    />
                  </td>
                  <td>
                    <FlagCell item={item} />
                  </td>
                  <td>
                    <RowActionMenu
                      item={item}
                      disabled={!workspaceWritesEnabled}
                      isWorking={workingActionIds.includes(`type:${item.documentId}`)}
                      isWithdrawWorking={workingActionIds.includes(`withdraw:${item.documentId}`)}
                      isOpen={openMenuId === item.documentId}
                      onOpenChange={(open) => setOpenMenuId(open ? item.documentId : null)}
                      onAcceptType={onAcceptType}
                      onStartType={onStartType}
                      onOpenExtraction={onOpenExtraction}
                      onOpenManualEntry={onOpenManualEntry}
                      onProcess={onProcessDocument}
                      onWithdraw={onWithdraw}
                      onReinstate={onReinstate}
                      onToggleHistory={onToggleHistory}
                    />
                  </td>
                </tr>
                {expandedHistoryIds.includes(item.documentId) ? (
                  <tr className="s1-history-row">
                    <td colSpan={9}>
                      <HistoryList intents={auditIntents.filter((intent) => intent.documentId === item.documentId)} />
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
  );
}

function TypeCell({
  item,
  editing,
  disabled,
  isWorking,
  onAcceptType,
  onStartType,
  onChangeType,
}: {
  item: EvidenceItem;
  editing: boolean;
  disabled: boolean;
  isWorking: boolean;
  onAcceptType: (documentId: string) => void;
  onStartType: (documentId: string) => void;
  onChangeType: (documentId: string, type: string) => void;
}) {
  if (!item.detectedType) {
    return <span className="s1-muted">not typed</span>;
  }

  if (editing) {
    return (
      <select className="s1-inline-input" defaultValue={item.detectedType} onChange={(event) => onChangeType(item.documentId, event.target.value)}>
        <option>Electric utility bill</option>
        <option>Corporate inventory workbook</option>
        <option>Stationary fuel consumption record</option>
        <option>Mobile fuel consumption record</option>
      </select>
    );
  }

  return (
    <div className="s1-type-cell">
      <div className="s1-type-name">{item.detectedType}</div>
      {item.typeReviewBand === "auto_accepted" ? (
        <div className="s1-type-band-text">auto-accepted</div>
      ) : item.typeReviewBand ? (
        <div className="s1-chip-stack">
          <StateIndicator dimension="readiness" value="non-blocking" label="open" explain={item.typeReviewReason ?? undefined} />
          <span className="s1-reason">{item.typeReviewReason}</span>
        </div>
      ) : null}
      <div className="s1-actions">
        <button
          className="s1-linklike"
          type="button"
          disabled={disabled || isWorking}
          title={disabled ? BACKEND_DISABLED_REASON : undefined}
          onClick={() => onAcceptType(item.documentId)}
        >
          {isWorking ? "Working" : "Accept"}
        </button>
        <button
          className="s1-linklike"
          type="button"
          disabled={disabled || isWorking}
          title={disabled ? BACKEND_DISABLED_REASON : undefined}
          onClick={() => onStartType(item.documentId)}
        >
          {isWorking ? "Working" : "Change"}
        </button>
      </div>
    </div>
  );
}

function RowActionMenu({
  item,
  disabled,
  isWorking,
  isWithdrawWorking,
  isOpen,
  onOpenChange,
  onAcceptType,
  onStartType,
  onOpenExtraction,
  onOpenManualEntry,
  onProcess,
  onWithdraw,
  onReinstate,
  onToggleHistory,
}: {
  item: EvidenceItem;
  disabled: boolean;
  isWorking: boolean;
  isWithdrawWorking: boolean;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
  onAcceptType: (documentId: string) => void;
  onStartType: (documentId: string) => void;
  onOpenExtraction: (documentId: string) => void;
  onOpenManualEntry: (documentId: string) => void;
  onProcess?: (documentId: string) => void;
  onWithdraw: (documentId: string) => void;
  onReinstate: (documentId: string) => void;
  onToggleHistory: (documentId: string) => void;
}) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const itemsRef = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    if (!isOpen) return;
    itemsRef.current[0]?.focus();
    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (menuRef.current?.contains(target) || triggerRef.current?.contains(target)) return;
      onOpenChange(false);
      triggerRef.current?.focus();
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [isOpen, onOpenChange]);

  function closeMenu() {
    onOpenChange(false);
    triggerRef.current?.focus();
  }

  function moveFocus(currentIndex: number, direction: 1 | -1) {
    const candidates = itemsRef.current.filter(Boolean) as HTMLButtonElement[];
    if (candidates.length === 0) return;
    const next = (currentIndex + direction + candidates.length) % candidates.length;
    candidates[next]?.focus();
  }

  const endpointTitle = disabled ? BACKEND_DISABLED_REASON : undefined;
  const noDetectedType = !item.detectedType;
  const isWithdrawn = item.disposition === "withdrawn";
  const allDisabled = disabled && noDetectedType;

  return (
    <div className="s1-menu">
      <button
        ref={triggerRef}
        className="s1-button s1-button--icon"
        type="button"
        aria-label={`Actions for ${item.filename}`}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        disabled={isWorking || isWithdrawWorking}
        onClick={() => onOpenChange(!isOpen)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onOpenChange(true);
          }
        }}
      >
        {isWorking || isWithdrawWorking ? "Working" : "..."}
      </button>
      {isOpen ? (
        <div className="s1-menu__panel" role="menu" ref={menuRef}>
          {allDisabled ? <div className="s1-menu__empty">{BACKEND_DISABLED_REASON}</div> : null}
          {[
            {
              label: "Accept detected type",
              disabled: disabled || noDetectedType || isWorking || isWithdrawn,
              title: noDetectedType ? "No detected type to accept." : endpointTitle,
              action: () => onAcceptType(item.documentId),
            },
            {
              label: "Change type",
              disabled: disabled || isWorking || isWithdrawn,
              title: endpointTitle,
              action: () => onStartType(item.documentId),
            },
            {
              label: "Open extraction review",
              disabled: item.fieldsExtracted === 0,
              title: item.fieldsExtracted === 0 ? "No extracted fields are available. Enter values manually instead." : undefined,
              action: () => onOpenExtraction(item.documentId),
            },
            {
              label: "Enter values manually",
              disabled: false,
              title: undefined,
              action: () => onOpenManualEntry(item.documentId),
            },
            {
              label: "Re-extract",
              disabled: !onProcess || isWorking || isWithdrawn,
              title: onProcess ? undefined : BACKEND_DISABLED_REASON,
              action: () => onProcess?.(item.documentId),
            },
            {
              label: "History",
              disabled: false,
              title: undefined,
              action: () => onToggleHistory(item.documentId),
            },
            {
              label: isWithdrawn ? "Reinstate document" : "Withdraw document",
              disabled: disabled || isWithdrawWorking,
              title: disabled ? endpointTitle : undefined,
              action: () => (isWithdrawn ? onReinstate(item.documentId) : onWithdraw(item.documentId)),
            },
          ].map((action, index) => (
            <button
              key={action.label}
              ref={(node) => {
                itemsRef.current[index] = node;
              }}
              className="s1-menu__item"
              type="button"
              role="menuitem"
              disabled={action.disabled}
              title={action.title}
              onClick={() => {
                if (!action.disabled) action.action();
                closeMenu();
              }}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  moveFocus(index, 1);
                }
                if (event.key === "ArrowUp") {
                  event.preventDefault();
                  moveFocus(index, -1);
                }
                if (event.key === "Escape") {
                  event.preventDefault();
                  closeMenu();
                }
              }}
            >
              {action.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function FacilityCell({
  item,
  editing,
  facilities,
  disabled,
  isWorking,
  onStart,
  onAssign,
}: {
  item: EvidenceItem;
  editing: boolean;
  facilities: EngagementConfig["facilities"];
  disabled: boolean;
  isWorking: boolean;
  onStart: (documentId: string) => void;
  onAssign: (documentId: string, facilityId: string) => void;
}) {
  if (editing) {
    return (
      <select className="s1-inline-input" defaultValue="" onChange={(event) => onAssign(item.documentId, event.target.value)}>
        <option value="" disabled>
          Assign facility
        </option>
        {facilities.map((facility) => (
          <option value={facility.facilityId} key={facility.facilityId}>
            {facility.name}
          </option>
        ))}
      </select>
    );
  }

  if (item.facilityState === "resolved") {
    return <span>{item.facilityName}</span>;
  }
  if (item.facilityState === "multiple") {
    return <StateIndicator dimension="facilityResolution" value="multiple" label={`Multiple (${item.facilityCount ?? 2})`} />;
  }
  if (item.facilityState === "not_facility_scoped") {
    return <StateIndicator dimension="facilityResolution" value="not_facility_scoped" label="Not facility-scoped" />;
  }
  return (
    <div>
      <StateIndicator dimension="facilityResolution" value="unresolved" label="Unresolved" />
      <div>
        <button
          className="s1-linklike"
          type="button"
          disabled={disabled || isWorking}
          title={disabled ? BACKEND_DISABLED_REASON : undefined}
          onClick={() => onStart(item.documentId)}
        >
          {isWorking ? "Working" : "Assign facility"}
        </button>
      </div>
    </div>
  );
}

function PeriodCell({
  item,
  editing,
  draft,
  disabled,
  isWorking,
  onStart,
  onDraft,
  onAssign,
}: {
  item: EvidenceItem;
  editing: boolean;
  draft: { start: string; end: string };
  disabled: boolean;
  isWorking: boolean;
  onStart: (documentId: string) => void;
  onDraft: (draft: { start: string; end: string }) => void;
  onAssign: (documentId: string) => void;
}) {
  if (editing) {
    return (
      <div className="s1-chip-stack">
        <input className="s1-inline-input" type="date" value={draft.start} onChange={(event) => onDraft({ ...draft, start: event.target.value })} />
        <input className="s1-inline-input" type="date" value={draft.end} onChange={(event) => onDraft({ ...draft, end: event.target.value })} />
        <button className="s1-button" type="button" disabled={isWorking} onClick={() => onAssign(item.documentId)}>
          {isWorking ? "Working" : "Save"}
        </button>
      </div>
    );
  }
  if (item.periodState === "resolved") {
    return (
      <span>
        {item.periodStart}
        <br />
        {item.periodEnd}
      </span>
    );
  }
  if (item.periodState === "spans_multiple") {
    return <StateIndicator dimension="periodResolution" value="spans_multiple" label="Spans multiple" />;
  }
  return (
    <div>
      <StateIndicator dimension="periodResolution" value="unresolved" label="Unresolved" />
      <div>
        <button
          className="s1-linklike"
          type="button"
          disabled={disabled || isWorking}
          title={disabled ? BACKEND_DISABLED_REASON : undefined}
          onClick={() => onStart(item.documentId)}
        >
          {isWorking ? "Working" : "Assign period"}
        </button>
      </div>
    </div>
  );
}

function ProcessingCell({
  item,
  isProcessing,
  onProcess,
}: {
  item: EvidenceItem;
  isProcessing: boolean;
  onProcess?: (documentId: string) => void;
}) {
  const labelByState: Record<ProcessingState, string> = {
    not_ingested: "Not ingested",
    ingested: "Ingested",
    typed: "Typed",
    extracted: "Extracted",
    blocked: "Blocked",
  };
  return (
    <div>
      <StateIndicator dimension="processing" value={item.processingState} label={labelByState[item.processingState]} />
      {item.processingState === "blocked" ? <div className="s1-reason">{item.haltReason}</div> : null}
      {onProcess && item.processingState !== "extracted" ? (
        <button
          className="s1-button s1-button--compact"
          type="button"
          disabled={isProcessing}
          onClick={() => onProcess(item.documentId)}
        >
          {isProcessing ? "Processing" : "Process"}
        </button>
      ) : null}
    </div>
  );
}

function FlagCell({ item }: { item: EvidenceItem }) {
  const relationshipLabels = item.relationships.map((relationship) => {
    const labels = {
      duplicate: "duplicate",
      superseded_by: "superseded by",
      supersedes: "supersedes",
      conflicting_value: "conflicting value",
    };
    return `${labels[relationship.kind]} ${relationship.otherDocumentId}`;
  });
  const propertyLabels = item.documentProperties.map((property) => {
    const labels = {
      poor_scan: "poor scan quality",
      foreign_language: "foreign language",
      password_protected: "password protected",
    };
    return labels[property];
  });
  if (relationshipLabels.length + propertyLabels.length === 0) {
    return <span className="s1-muted">none</span>;
  }
  return (
    <div className="s1-chip-stack">
      {relationshipLabels.map((label) => (
        <span key={label}>{label}</span>
      ))}
      {propertyLabels.map((label) => (
        <em key={label}>{label}</em>
      ))}
    </div>
  );
}

function SupportiveEvidenceCards({ items }: { items: EvidenceItem[] }) {
  if (items.length === 0) return null;
  return (
    <section className="s1-supportive-evidence" aria-label="Supportive evidence">
      <div className="s1-supportive-evidence__label">Supportive evidence</div>
      {items.map((item) => (
        <article className="s1-supportive-card" key={item.documentId}>
          <h3>{item.filename}</h3>
          <div className="s1-supportive-card__meta">
            <span>{item.reviewArea}</span>
            <span>{item.uploadedBy.name} · {new Date(item.uploadedAt).toLocaleDateString()}</span>
          </div>
          <p>{item.note}</p>
        </article>
      ))}
    </section>
  );
}

function CompletenessPanel() {
  return (
    <section className="s1-panel">
      <h3>Completeness</h3>
      <table className="s1-printable-table">
        <thead>
          <tr>
            <th align="left">Category</th>
            <th align="left">Populated</th>
            <th align="left">not yet</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>In-scope field list</td>
            <td colSpan={2}>{EXACT_COPY.dependencyBlocked}</td>
          </tr>
        </tbody>
      </table>
    </section>
  );
}

function NonRetentionNotice() {
  return (
    <section className="s1-panel s1-notice" role="status">
      <strong>Audit entries in this session are not retained.</strong>
      <span>This build cannot be used for a live engagement.</span>
    </section>
  );
}

function ActivityRegion({ intents }: { intents: SessionAuditEntry[] }) {
  const newest = [...intents].reverse();
  return (
    <section className="s1-panel">
      <details>
        <summary>Activity · {intents.length}</summary>
        {newest.length > 0 ? (
          <HistoryList intents={newest} />
        ) : (
          <p className="s1-muted">No session activity yet.</p>
        )}
      </details>
    </section>
  );
}

function HistoryList({ intents }: { intents: SessionAuditEntry[] }) {
  if (intents.length === 0) {
    return <p className="s1-muted">No history for this row in this session.</p>;
  }
  return (
    <div className="s1-history-list">
      {intents.map((intent) => (
        <article
          className={`s1-history-entry s1-history-entry--${intent.actor.actorType}`}
          key={intent.entryId}
        >
          <div>
            <strong>{actionLabel(intent.action)}</strong>
            <span className="s1-muted"> · {intent.documentId}</span>
          </div>
          <div className="s1-mono s1-muted">
            {intent.actor.name} · {new Date(intent.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </div>
          <div className="s1-muted">
            {formatAuditValue(intent.oldValue)} -&gt; {formatAuditValue(intent.newValue)}
          </div>
        </article>
      ))}
    </div>
  );
}

function actionLabel(action: SessionAuditEntry["action"]) {
  return action.replaceAll("_", " ");
}

function formatAuditValue(value: SessionAuditEntry["oldValue"]) {
  if (value === null || value === undefined) return "not found";
  return String(value);
}

function groupItems(items: EvidenceItem[], groupBy: GroupBy) {
  if (groupBy === "none") {
    return [{ label: null, items }];
  }
  const groups = new Map<string, EvidenceItem[]>();
  items.forEach((item) => {
    const label =
      groupBy === "facility"
        ? item.facilityName ?? item.facilityState.replaceAll("_", " ")
        : groupBy === "period"
          ? item.periodState === "resolved"
            ? `${item.periodStart} to ${item.periodEnd}`
            : item.periodState.replaceAll("_", " ")
          : item.detectedType ?? "not typed";
    groups.set(label, [...(groups.get(label) ?? []), item]);
  });
  return Array.from(groups.entries()).map(([label, groupItems]) => ({ label, items: groupItems }));
}

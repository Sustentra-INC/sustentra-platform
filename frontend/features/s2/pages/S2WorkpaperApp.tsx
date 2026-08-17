"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import {
  ACTIONS,
  ACTION_WITH,
  CONTAINER,
  FINDING_TYPE,
  GROUP,
  REQUEST_STATE,
} from "../constants/copy";
import { getInventory, type S2FixtureMode } from "../fixtures/getInventory";
import type { Ask, Finding, FindingState, FindingType, InventoryLine, RequestRecord, Requirement } from "../types";
import {
  AskCard,
  CalculationStrip,
  ChangeItem,
  ContainerState,
  CoverageGrid,
  DocumentRow,
  ExaminationRecord,
  FindingRow,
  InventoryLineRow,
  ProcedureRow,
  RequestRow,
  RequirementRow,
  StateChip,
  type User,
} from "../components";
import { persist } from "../persistence/persist";
import { findingDedupeKey } from "../utils/findingKey";
import { getLastSeen, setLastSeen } from "../utils/lastSeen";
import type { ChangeItem as ChangeItemType, DocumentRecord, Procedure } from "../types";

type FilterMode = "all" | "verification team" | "responsible party" | "independent reviewer";
type OrderMode = "quantity" | "facility" | "category";
type S2View =
  | { name: "inventory" }
  | { name: "line"; lineId: string; focusedRequirementId?: string }
  | { name: "examine"; lineId: string; requirementId: string }
  | { name: "requestBuilder"; requirementIds: string[]; fromLineId?: string }
  | { name: "openRequests" }
  | { name: "findings"; lineId?: string; requirementId?: string }
  | { name: "documents"; lineId?: string; requestId?: string }
  | { name: "analytical" }
  | { name: "coverage"; mode?: "fixture" | "live" };

const REQUIREMENT_GROUPS = ["activity", "factors", "boundary", "calculation"] as const;
const CHANGE_STAMP = "2026-08-17T00:00:00Z";

const CURRENT_USER: User = { id: "user-cyang", name: "C. Yang" };

export function S2WorkpaperApp() {
  const [fixtureMode, setFixtureMode] = useState<S2FixtureMode>("meridian");
  const [filterMode, setFilterMode] = useState<FilterMode>("all");
  const [orderMode, setOrderMode] = useState<OrderMode>("quantity");
  const [assignedUsers, setAssignedUsers] = useState<Record<string, User | undefined>>({});
  const [view, setView] = useState<S2View>({ name: "inventory" });
  const [recordState, setRecordState] = useState<Record<string, { selected: string[]; note: string; conclusion?: "noExceptions" | FindingType }>>({});
  const [requestRows, setRequestRows] = useState<RequestRecord[] | null>(null);
  const [findingRows, setFindingRows] = useState<Finding[] | null>(null);
  const [changesOpen, setChangesOpen] = useState(false);
  const [changesSeen, setChangesSeen] = useState(false);
  const lastLineScrollRef = useRef(0);
  const changesButtonRef = useRef<HTMLButtonElement>(null);
  const data = getInventory(fixtureMode);
  const currentRequests = requestRows ?? data.requests;
  const currentFindings = findingRows ?? data.findings;

  const metrics = useMemo(() => workspaceMetrics(data.lines, data.requirements, currentFindings), [data.lines, data.requirements, currentFindings]);
  const rows = useMemo(() => {
    const withDerived = data.lines.map((line) => deriveLineView(line, data.requirements, currentFindings));
    const filtered = fixtureMode === "meridian-filtered-empty"
      ? []
      : filterMode === "all"
        ? withDerived
        : withDerived.filter((line) => line.actionWith === filterMode);
    return [...filtered].sort((left, right) => {
      if (orderMode === "facility") return left.line.facility.localeCompare(right.line.facility);
      if (orderMode === "category") return left.line.category.localeCompare(right.line.category);
      return right.line.quantityTCO2e - left.line.quantityTCO2e;
    });
  }, [data.lines, data.requirements, currentFindings, filterMode, fixtureMode, orderMode]);

  const containerState = modeToContainerState(fixtureMode, rows.length);
  const changeGroups = buildChangeGroups();
  const changeCount = changeGroups.reduce((count, group) => count + group.items.length, 0);

  useEffect(() => {
    const seen = getLastSeen() === CHANGE_STAMP;
    setChangesSeen(seen);
    if (!seen) setChangesOpen(true);
  }, []);

  function closeChanges() {
    setChangesOpen(false);
    window.setTimeout(() => changesButtonRef.current?.focus(), 0);
  }

  function markChangesSeen() {
    setLastSeen(CHANGE_STAMP);
    setChangesSeen(true);
    closeChanges();
  }

  return (
    <main className="s2-shell">
      <section className="s2-header-band s2-header-band--identity">
        <div>
          <h1>{data.engagement.client}</h1>
          <div className="s2-subline">{data.engagement.id} · {data.engagement.period}</div>
        </div>
        <button className="s2-count-tile s2-change-counter" type="button" ref={changesButtonRef} onClick={() => setChangesOpen(true)} aria-label={`${changesSeen ? 0 : changeCount} changes since you were last here`}>
          <span className="s2-num">{changesSeen ? 0 : changeCount}</span>
          <span>Since you were last here</span>
        </button>
        <div className="s2-header-grid">
          <Meta label="Regulation" value={data.engagement.regulation} />
          <Meta label="Standard" value={data.engagement.standard} />
          <Meta label="Assurance" value={data.engagement.assuranceLevel} />
          <Meta label="Boundary" value={data.engagement.consolidation} />
        </div>
      </section>

      <section className="s2-header-band s2-header-band--summary">
        <strong>{data.lines.length} reported lines</strong>
        <span className="s2-num">{data.engagement.reportedTotalTCO2e.toLocaleString()} tCO2e</span>
        <span>{data.engagement.facilities.join(" · ")}</span>
      </section>

      <section className="s2-dependency-banner" role="status" aria-label={CONTAINER.blocked} aria-live="polite">
        <strong>{CONTAINER.blocked}</strong>
        <span>{CONTAINER.blockedHint}</span>
      </section>

      <section className="s2-count-tiles" aria-label="Inventory counts">
        <CountTile label="Lines" value={data.lines.length} />
        <CountTile label="Examined" value={metrics.examined} />
        <CountTile label="With client" value={metrics.withClient} />
        <CountTile label="Findings" value={metrics.findings} />
        <CountTile label="Unassigned" value={data.lines.filter((line) => !assignedUsers[line.id]).length} />
      </section>

      <section className="s2-toolbar" aria-label="Inventory controls">
        <label>
          Action with
          <select value={filterMode} onChange={(event) => setFilterMode(event.target.value as FilterMode)}>
            <option value="all">All</option>
            <option value={ACTION_WITH.team}>{ACTION_WITH.team}</option>
            <option value={ACTION_WITH.client}>{ACTION_WITH.client}</option>
            <option value={ACTION_WITH.reviewer}>{ACTION_WITH.reviewer}</option>
          </select>
        </label>
        <label>
          Order
          <select value={orderMode} onChange={(event) => setOrderMode(event.target.value as OrderMode)}>
            <option value="quantity">reported quantity descending</option>
            <option value="facility">facility</option>
            <option value="category">category</option>
          </select>
        </label>
        <label>
          Fixture
          <select value={fixtureMode} onChange={(event) => setFixtureMode(event.target.value as S2FixtureMode)}>
            <option value="meridian">meridian</option>
            <option value="meridian-empty">empty</option>
            <option value="meridian-none-examined">none examined</option>
            <option value="meridian-filtered-empty">filtered empty</option>
            <option value="meridian-loading">loading</option>
            <option value="meridian-error">error</option>
            <option value="meridian-degraded">degraded</option>
            <option value="meridian-blocked">blocked</option>
            <option value="meridian-complete">complete</option>
          </select>
        </label>
        <button className="s2-button" type="button" onClick={() => setView({ name: "openRequests" })}>Open requests</button>
        <button className="s2-button" type="button" onClick={() => setView({ name: "findings" })}>Findings</button>
        <button className="s2-button" type="button" onClick={() => setView({ name: "documents" })}>Documents</button>
        <button className="s2-button" type="button" onClick={() => setView({ name: "analytical" })}>Analytical procedures</button>
        <button className="s2-button" type="button" onClick={() => setView({ name: "coverage", mode: "fixture" })}>Check Coverage</button>
        <button className="s2-button" type="button" onClick={() => setView({ name: "findings" })}>{ACTIONS.raiseFinding}</button>
        <button className="s2-button" type="button" onClick={() => setView({ name: "requestBuilder", requirementIds: requestableRequirementIds(data.requirements) })}>{ACTIONS.request}</button>
      </section>

      {view.name === "inventory" && containerState ? (
        <ContainerState
          state={containerState}
          detail={{
            lines: data.lines.length,
            total: data.engagement.reportedTotalTCO2e.toLocaleString(),
            at: "Friday 14 August",
            loaded: data.lines.length,
            missing: data.missingLineNames,
          }}
          onAction={() => {
            setFixtureMode("meridian");
            setFilterMode("all");
          }}
        />
      ) : view.name === "inventory" ? (
        <ReportedInventoryTable
          rows={rows}
          assignedUsers={assignedUsers}
          onOpenLine={(lineId) => {
            lastLineScrollRef.current = typeof window === "undefined" ? 0 : window.scrollY;
            setView({ name: "line", lineId });
          }}
          onAssign={(lineId, user) => {
            persist("assignment", { lineId, assignee: user?.id ?? null });
            setAssignedUsers((current) => ({ ...current, [lineId]: user }));
          }}
        />
      ) : view.name === "line" ? (
        <InventoryLineView
          line={data.lines.find((line) => line.id === view.lineId)}
          requirements={data.requirements.filter((requirement) => requirement.lineId === view.lineId)}
          findings={currentFindings}
          focusedRequirementId={view.focusedRequirementId}
          onBack={() => {
            setView({ name: "inventory" });
            window.setTimeout(() => window.scrollTo({ top: lastLineScrollRef.current }), 0);
          }}
          onOpenRequirement={(requirementId) => setView({ name: "examine", lineId: view.lineId, requirementId })}
          onRequestRequirements={(requirementIds) => setView({ name: "requestBuilder", requirementIds, fromLineId: view.lineId })}
          onRaiseFinding={(requirementId) => setView({ name: "findings", lineId: view.lineId, requirementId })}
        />
      ) : view.name === "examine" ? (
        <ExamineRequirementView
          line={data.lines.find((line) => line.id === view.lineId)}
          requirements={data.requirements.filter((requirement) => requirement.lineId === view.lineId)}
          requirementId={view.requirementId}
          findings={currentFindings}
          recordState={recordState[view.requirementId] ?? { selected: [], note: "" }}
          onPatchRecord={(patch) =>
            setRecordState((current) => ({
              ...current,
              [view.requirementId]: { ...(current[view.requirementId] ?? { selected: [], note: "" }), ...patch },
            }))
          }
          onBack={(focusedRequirementId = view.requirementId) => setView({ name: "line", lineId: view.lineId, focusedRequirementId })}
          onMove={(requirementId) => setView({ name: "examine", lineId: view.lineId, requirementId })}
          onRaiseFinding={(requirementId) => setView({ name: "findings", lineId: view.lineId, requirementId })}
        />
      ) : view.name === "requestBuilder" ? (
        <RequestBuilderView
          requirements={data.requirements.filter((requirement) => view.requirementIds.includes(requirement.id))}
          allRequirements={data.requirements}
          onBack={() => view.fromLineId ? setView({ name: "line", lineId: view.fromLineId }) : setView({ name: "inventory" })}
          onSaveRequest={(request) => setRequestRows((current) => [...(current ?? data.requests), request])}
          onOpenRequests={() => setView({ name: "openRequests" })}
        />
      ) : view.name === "openRequests" ? (
        <OpenRequestsView
          requests={currentRequests}
          onBack={() => setView({ name: "inventory" })}
          onUpdateRequests={setRequestRows}
        />
      ) : view.name === "documents" ? (
        <DocumentsView
          documents={data.documents}
          requirements={data.requirements}
          lines={data.lines}
          requests={currentRequests}
          initialLineId={view.lineId}
          initialRequestId={view.requestId}
          onBack={() => setView({ name: "inventory" })}
        />
      ) : view.name === "analytical" ? (
        <AnalyticalProceduresView
          procedures={buildAnalyticalProcedures()}
          onBack={() => setView({ name: "inventory" })}
        />
      ) : view.name === "coverage" ? (
        <CoverageCheckView
          mode={view.mode ?? "fixture"}
          lines={data.lines}
          findings={currentFindings}
          onBack={() => setView({ name: "inventory" })}
          onMode={(mode) => setView({ name: "coverage", mode })}
        />
      ) : (
        <FindingsView
          findings={currentFindings}
          focus={{ lineId: view.lineId, requirementId: view.requirementId }}
          onBack={() => view.lineId ? setView({ name: "line", lineId: view.lineId, focusedRequirementId: view.requirementId }) : setView({ name: "inventory" })}
          onUpdateFindings={setFindingRows}
        />
      )}
      {changesOpen ? <ChangesSlideOver groups={changeGroups} empty={changesSeen} onClose={closeChanges} onMarkAllSeen={markChangesSeen} /> : null}
    </main>
  );
}

function ReportedInventoryTable({
  rows,
  assignedUsers,
  onOpenLine,
  onAssign,
}: {
  rows: ReturnType<typeof deriveLineView>[];
  assignedUsers: Record<string, User | undefined>;
  onOpenLine: (lineId: string) => void;
  onAssign: (lineId: string, user?: User) => void;
}) {
  return (
    <div className="s2-table-wrap">
      <table className="s2-table">
        <thead>
          <tr>
            <th>Reported line</th>
            <th className="s2-num">tCO2e</th>
            <th>Progress</th>
            <th className="s2-num">Needs action</th>
            <th>Action with</th>
            <th>Findings</th>
            <th>Assigned to</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <InventoryLineRow
              key={row.line.id}
              line={row.line}
              progress={row.progress}
              outstanding={row.needsAction}
              actionWith={row.actionWith}
              findingCounts={row.findingCounts}
              assignedTo={assignedUsers[row.line.id]}
              onOpen={() => onOpenLine(row.line.id)}
              onAssign={(user) => onAssign(row.line.id, user ?? CURRENT_USER)}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InventoryLineView({
  line,
  requirements,
  findings,
  focusedRequirementId,
  onBack,
  onOpenRequirement,
  onRequestRequirements,
  onRaiseFinding,
}: {
  line?: InventoryLine;
  requirements: Requirement[];
  findings: Finding[];
  focusedRequirementId?: string;
  onBack: () => void;
  onOpenRequirement: (requirementId: string) => void;
  onRequestRequirements: (requirementIds: string[]) => void;
  onRaiseFinding: (requirementId?: string) => void;
}) {
  if (!line) return <ContainerState state="error" detail={{ at: "unknown line" }} onAction={onBack} />;
  const lineView = deriveLineView(line, requirements, findings);
  const byGroup = new Map(REQUIREMENT_GROUPS.map((group) => [group, requirements.filter((requirement) => requirement.group === group)]));
  return (
    <section className="s2-line-view">
      <div className="s2-header-band">
        <div>
          <button className="s2-back-link" type="button" onClick={onBack}>Back to Reported Inventory</button>
          <h1>{line.facility} · Scope {line.scope} · {line.category}</h1>
          <div className="s2-subline">
            <span className="s2-num">{line.quantityTCO2e.toLocaleString()} tCO2e</span>
            <span> · materiality multiple {(line.quantityTCO2e / 2500).toFixed(1)}x</span>
          </div>
        </div>
      </div>
      <CalculationStrip
        inputs={calculationInputsForLine(line)}
        result={{ value: `${line.quantityTCO2e.toLocaleString()} tCO2e` }}
        unheldShare={line.id === "LN-RICH-S1-STC" ? 18 : undefined}
      />
      <section className="s2-toolbar">
        <button className="s2-button" type="button" onClick={() => persist("assignment", { lineId: line.id, assignee: CURRENT_USER.id })}>{ACTIONS.assignToMe}</button>
        <button className="s2-button" type="button" onClick={() => onRequestRequirements(requestableRequirementIds(requirements))}>Request all needs action</button>
        <button className="s2-button" type="button" onClick={() => onRaiseFinding()}>{ACTIONS.raiseFinding}</button>
      </section>
      <div className="s2-table-wrap">
        <table className="s2-table">
          <thead>
            <tr>
              <th>What has to be true</th>
              <th>Evidence</th>
              <th>Review</th>
              <th>Findings</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {REQUIREMENT_GROUPS.flatMap((group) => {
              const groupRequirements = byGroup.get(group) ?? [];
              const examined = groupRequirements.filter((requirement) =>
                requirement.reviewState === "examined — no exceptions" ||
                requirement.reviewState === "examined — findings raised"
              ).length;
              return [
                <tr className="s2-group-row" data-testid={`s2-requirement-group-${group}`} key={`${group}-header`}>
                  <td colSpan={5}>
                    <strong>{GROUP[group]}</strong>
                    <span className="s2-subline">{groupRequirements.length} requirements · {examined} examined</span>
                  </td>
                </tr>,
                ...groupRequirements.map((requirement) => (
                  <RequirementRow
                    key={requirement.id}
                    requirement={requirement}
                    findings={findings.filter((finding) => requirement.findingIds.includes(finding.id))}
                    onOpen={() => onOpenRequirement(requirement.id)}
                    onInlineAction={(action) => {
                      persist("examination", { action, requirementId: requirement.id });
                      if (action === "request") onRequestRequirements([requirement.id]);
                      if (action === "reExamine") onOpenRequirement(requirement.id);
                    }}
                  />
                )),
              ];
            })}
          </tbody>
        </table>
      </div>
      {focusedRequirementId ? <div className="s2-subline">Returned to {focusedRequirementId}</div> : null}
      <div className="s2-subline">{lineView.progress.examined} of {lineView.progress.total} examined</div>
    </section>
  );
}

function ExamineRequirementView({
  line,
  requirements,
  requirementId,
  findings,
  recordState,
  onPatchRecord,
  onBack,
  onMove,
  onRaiseFinding,
}: {
  line?: InventoryLine;
  requirements: Requirement[];
  requirementId: string;
  findings: Finding[];
  recordState: { selected: string[]; note: string; conclusion?: "noExceptions" | FindingType };
  onPatchRecord: (patch: Partial<{ selected: string[]; note: string; conclusion?: "noExceptions" | FindingType }>) => void;
  onBack: (focusedRequirementId?: string) => void;
  onMove: (requirementId: string) => void;
  onRaiseFinding: (requirementId: string) => void;
}) {
  const requirement = requirements.find((candidate) => candidate.id === requirementId);
  if (!line || !requirement) return <ContainerState state="error" detail={{ at: "unknown requirement" }} onAction={() => onBack()} />;
  const activeLine: InventoryLine = line;
  const activeRequirement: Requirement = requirement;
  const currentIndex = requirements.findIndex((candidate) => candidate.id === requirementId);
  const previous = requirements[currentIndex - 1];
  const next = requirements[currentIndex + 1];
  const mode = activeRequirement.evidenceState === "partially held" ? "partial" : "normal";
  const itemFindings = findings.filter((finding) => activeRequirement.findingIds.includes(finding.id));
  const evidenceDetail = evidenceDetailForRequirement(activeLine, activeRequirement);

  useEffect(() => {
    const firstTechnique = document.querySelector<HTMLButtonElement>(".s2-examine-view .s2-technique");
    firstTechnique?.focus();
  }, [activeRequirement.id]);

  function recordAndMove(moveNext: boolean) {
    persist("examination", {
      requirementId: activeRequirement.id,
      selected: recordState.selected,
      conclusion: recordState.conclusion,
      note: recordState.note,
    });
    if (moveNext && next && next.evidenceState !== "no evidence held") {
      onMove(next.id);
    } else if (moveNext) {
      onBack(next?.id ?? activeRequirement.id);
    }
  }

  function handleKeys(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onBack(activeRequirement.id);
    }
    if (event.key === "Enter") {
      event.preventDefault();
      recordAndMove(true);
    }
    if (event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (next && next.evidenceState !== "no evidence held") onMove(next.id);
      else onBack(next?.id ?? activeRequirement.id);
    }
    if (event.key.toLowerCase() === "a") {
      event.preventDefault();
      onPatchRecord({ conclusion: "noExceptions" });
    }
    const shortcut = Number(event.key);
    if (shortcut >= 1 && shortcut <= 4) {
      const technique = ["inquiry", "analytical testing", "examination", "cross-checking"][shortcut - 1] ?? "inquiry";
      onPatchRecord({ selected: recordState.selected.includes(technique) ? recordState.selected : [...recordState.selected, technique] });
    }
  }

  return (
    <section className="s2-examine-view" onKeyDown={handleKeys}>
      <main className="s2-examine-main">
        <button className="s2-inline-action" type="button" onClick={() => onBack(activeRequirement.id)}>
          {activeLine.facility} · {activeLine.category}
        </button>
        <h1>{activeRequirement.label}</h1>
        <p>{activeRequirement.definition}</p>
        {mode === "partial" ? (
          <>
            <CoverageGrid
              axis={{ name: "Facility", values: ["Richmond", "Carson", "Bakersfield"] }}
              expected={9}
              heldCount={6}
              rows={[
                { label: "Gas invoices", held: [true, false, true], risk: "cut-off" },
                { label: "Fuel analysis", held: [true, true, false] },
                { label: "Monthly detail", held: [true, false, false], risk: "completeness" },
              ]}
            />
            <section className="s2-panel">
              <h2>Sufficiency</h2>
              <p>Carson Oct-Dec and Bakersfield monthly detail remain absent.</p>
              <button className="s2-button" type="button" onClick={() => persist("request", { requirementId: activeRequirement.id, action: "request missing part" })}>{ACTIONS.requestMissing}</button>
              <button className="s2-button" type="button" onClick={() => persist("examination", { requirementId: activeRequirement.id, action: "accept partial as sufficient" })}>{ACTIONS.acceptSufficient}</button>
            </section>
          </>
        ) : (
          <section className="s2-panel">
            <h2>Evidence</h2>
            <dl className="s2-evidence-list">
              <div>
                <dt>Governing source</dt>
                <dd>{evidenceDetail.governingSource}</dd>
              </div>
              <div>
                <dt>Other source</dt>
                <dd>{evidenceDetail.otherSource}</dd>
              </div>
              <div>
                <dt>Trace</dt>
                <dd>{evidenceDetail.trace}</dd>
              </div>
            </dl>
            <blockquote>{evidenceDetail.snippet}</blockquote>
            <button className="s2-button" type="button">Open original</button>
          </section>
        )}
        <ExaminationRecord
          selected={recordState.selected}
          conclusion={recordState.conclusion}
          note={recordState.note}
          assuranceLevel="limited"
          performedBy={{ id: activeRequirement.performedBy ?? CURRENT_USER.id, name: displayPerson(activeRequirement.performedBy) }}
          performedAt={formatRecordTime(activeRequirement.performedAt)}
          onChange={(patch) => onPatchRecord(patch)}
          onRecord={recordAndMove}
        />
        <section className="s2-panel">
          <h2>Notes on this item</h2>
          <button className="s2-button" type="button" onClick={() => persist("note", { requirementId: activeRequirement.id, text: recordState.note })}>{ACTIONS.addNote}</button>
        </section>
        <section className="s2-panel">
          <h2>Findings on this item</h2>
          <div>{itemFindings.length} findings</div>
          <button className="s2-button" type="button" onClick={() => {
            persist("finding", { requirementId: activeRequirement.id, action: "raise from examine" });
            onRaiseFinding(activeRequirement.id);
          }}>{ACTIONS.raiseFinding}</button>
        </section>
        <div className="s2-actions">
          <button className="s2-button" type="button" disabled={!previous} onClick={() => previous ? onMove(previous.id) : undefined}>Previous</button>
          <button className="s2-button" type="button" disabled={!next} onClick={() => next ? onMove(next.id) : undefined}>Next</button>
        </div>
      </main>
      <aside className="s2-examine-rail">
        <section>
          <h2>This item</h2>
          <div className="s2-id">{activeRequirement.fieldId}</div>
          <StateChip value={activeRequirement.evidenceState} role={activeRequirement.evidenceState === "evidence held" ? "resolved" : "open"} />
          <StateChip value={activeRequirement.reviewState} role={activeRequirement.reviewState === "examination invalidated" ? "open" : "active"} />
          {invalidationDetailForRequirement(activeRequirement) ? <div className="s2-subline">{invalidationDetailForRequirement(activeRequirement)}</div> : null}
        </section>
        <section>
          <h2>Who</h2>
          <div>{activeRequirement.assignedTo ?? "unassigned"}</div>
        </section>
        <section>
          <h2>Blocked by this</h2>
          <div className="s2-num">{activeRequirement.blocksCount}</div>
        </section>
        <section>
          <h2>Platform coverage</h2>
          <div>{mode === "partial" ? "partially held" : "evidence held"}</div>
        </section>
      </aside>
    </section>
  );
}

function RequestBuilderView({
  requirements,
  allRequirements,
  onBack,
  onSaveRequest,
  onOpenRequests,
}: {
  requirements: Requirement[];
  allRequirements: Requirement[];
  onBack: () => void;
  onSaveRequest: (request: RequestRecord) => void;
  onOpenRequests: () => void;
}) {
  const [asks, setAsks] = useState<Ask[]>(() => buildAsksForRequirements(requirements));
  const [previewOpen, setPreviewOpen] = useState(false);
  const [working, setWorking] = useState<"save" | "send" | null>(null);
  const hasInternalId = asks.some((ask) => containsInternalId(ask.wording));
  const coveredIds = [...new Set(asks.flatMap((ask) => ask.satisfiesFieldIds))];

  function saveDraft(kind: "save" | "send") {
    setWorking(kind);
    const request: RequestRecord = {
      id: `REQ-DRAFT-${Date.now()}`,
      state: kind === "send" && !hasInternalId ? "sent" : "drafted",
      recipient: "m.osei@meridian-ig.com",
      sentAt: kind === "send" && !hasInternalId ? new Date().toISOString() : undefined,
      dueAt: kind === "send" && !hasInternalId ? "2026-08-24T00:00:00Z" : undefined,
      asks,
      itemsCovered: coveredIds.length,
      itemsSatisfied: 0,
    };
    persist("request", { action: kind, request });
    onSaveRequest(request);
    if (kind === "send" && !hasInternalId) onOpenRequests();
  }

  return (
    <section className="s2-outbound-view">
      <div className="s2-header-band">
        <div>
          <button className="s2-inline-action" type="button" onClick={onBack}>Back</button>
          <h1>Request Builder</h1>
          <div className="s2-subline">{coveredIds.length} requirements selected</div>
        </div>
      </div>
      {hasInternalId ? <div className="s2-inline-refusal">Client-facing wording cannot include Field_IDs or internal identifiers.</div> : null}
      <div className="s2-request-builder">
        {asks.map((ask, index) => (
          <AskCard
            ask={ask}
            satisfies={allRequirements.filter((requirement) => ask.satisfiesFieldIds.includes(requirement.fieldId))}
            editable
            key={`${ask.canonicalType}-${index}`}
            onEdit={(wording) => setAsks((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, wording } : item))}
            onSplit={() => setAsks((current) => splitAsk(current, index))}
            onMerge={(canonicalType) => setAsks((current) => mergeAsks(current, canonicalType))}
          />
        ))}
      </div>
      <section className="s2-panel">
        <h2>Satisfies</h2>
        <div className="s2-id">{coveredIds.join(", ")}</div>
      </section>
      <div className="s2-actions">
        {working ? <span className="s2-subline">Working</span> : null}
        <button className="s2-button" type="button" disabled={Boolean(working) || hasInternalId} onClick={() => saveDraft("save")}>Save draft</button>
        <button className="s2-button" type="button" onClick={() => setPreviewOpen(true)}>Preview message</button>
        <button className="s2-button s2-button--primary" type="button" disabled={Boolean(working) || hasInternalId} onClick={() => saveDraft("send")}>Send</button>
      </div>
      {previewOpen ? (
        <div className="s2-modal-backdrop" role="dialog" aria-modal="true" aria-label="Preview message">
          <section className="s2-modal">
            <h2>Preview message</h2>
            {asks.map((ask) => <p key={ask.canonicalType}>{ask.wording}</p>)}
            <button className="s2-button" type="button" onClick={() => setPreviewOpen(false)}>Close preview</button>
          </section>
        </div>
      ) : null}
    </section>
  );
}

function OpenRequestsView({
  requests,
  onBack,
  onUpdateRequests,
}: {
  requests: RequestRecord[];
  onBack: () => void;
  onUpdateRequests: (requests: RequestRecord[]) => void;
}) {
  const displayRequests = ensureRequestStates(requests);
  function updateRequest(requestId: string, action: "send" | "chase" | "withdraw" | "failSend") {
    persist("request", { requestId, action });
    onUpdateRequests(displayRequests.map((request) => {
      if (request.id !== requestId) return request;
      if (action === "withdraw") return { ...request, state: "withdrawn" };
      if (action === "send") return { ...request, state: "sent", sentAt: new Date().toISOString(), dueAt: request.dueAt ?? "2026-08-24T00:00:00Z" };
      if (action === "failSend") return { ...request, state: "drafted" };
      return request;
    }));
  }
  return (
    <section className="s2-outbound-view">
      <div className="s2-header-band">
        <div>
          <button className="s2-back-link" type="button" onClick={onBack}>Back to Reported Inventory</button>
          <h1>Open Requests</h1>
          <div className="s2-subline">Overdue is derived from due dates, not modeled as a request state.</div>
        </div>
      </div>
      <div className="s2-table-wrap">
        <table className="s2-table">
          <thead>
            <tr>
              <th>Request</th>
              <th>State</th>
              <th>Age</th>
              <th>Unblocks</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {displayRequests.map((request) => (
              <RequestRow
                key={request.id}
                request={request}
                unblocks={request.itemsCovered - request.itemsSatisfied}
                overdueDays={overdueDays(request)}
                onAction={(action) => updateRequest(request.id, action)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function FindingsView({
  findings,
  focus,
  onBack,
  onUpdateFindings,
}: {
  findings: Finding[];
  focus: { lineId?: string; requirementId?: string };
  onBack: () => void;
  onUpdateFindings: (findings: Finding[]) => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const focusFinding = buildRaisedFinding(focus);
  const displayFindings = focusFinding && !findings.some((finding) => findingDedupeKey(finding) === findingDedupeKey(focusFinding))
    ? [focusFinding, ...findings]
    : findings;
  const activeCount = displayFindings.filter((finding) => finding.state !== "withdrawn").length;
  function updateFinding(findingId: string, action: "putToClient" | "withdraw" | "reconsider" | "chase") {
    persist("finding", { findingId, action });
    onUpdateFindings(displayFindings.map((finding) => {
      if (finding.id !== findingId) return finding;
      if (action === "withdraw") return { ...finding, state: "withdrawn" };
      if (action === "putToClient") return { ...finding, state: "put to client" };
      if (action === "reconsider") return { ...finding, state: "raised" };
      return finding;
    }));
  }
  function bulkPutToClient() {
    persist("finding", { action: "bulk put to client", findingIds: selected });
    onUpdateFindings(displayFindings.map((finding) => selected.includes(finding.id) ? { ...finding, state: "put to client" } : finding));
    setSelected([]);
  }
  return (
    <section className="s2-outbound-view">
      <div className="s2-header-band">
        <div>
          <button className="s2-inline-action" type="button" onClick={onBack}>Back</button>
          <h1>Findings</h1>
          <div className="s2-subline"><span className="s2-num">{activeCount}</span> active findings</div>
        </div>
      </div>
      <div className="s2-actions">
        <button className="s2-button" type="button" onClick={bulkPutToClient} disabled={selected.length === 0}>Put selected to client</button>
      </div>
      {(["misstatement", "nonconformity", "clarification request"] as FindingType[]).map((type) => {
        const groupFindings = displayFindings.filter((finding) => finding.type === type);
        return (
          <section className="s2-panel" key={type}>
            <h2>{findingGroupLabel(type)}</h2>
            <div className="s2-table-wrap">
              <table className="s2-table">
                <thead>
                  <tr>
                    <th>Select</th>
                    <th>Line</th>
                    <th>Type</th>
                    <th>Summary</th>
                    <th>Magnitude</th>
                    <th>State</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {groupFindings.map((finding) => (
                    <FindingRow
                      key={finding.id}
                      finding={finding}
                      showLine
                      selected={selected.includes(finding.id)}
                      onSelect={(checked) => setSelected((current) => checked ? [...current, finding.id] : current.filter((id) => id !== finding.id))}
                      onAction={(action) => updateFinding(finding.id, action)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
    </section>
  );
}

function DocumentsView({
  documents,
  requirements,
  lines,
  requests,
  initialLineId,
  initialRequestId,
  onBack,
}: {
  documents: DocumentRecord[];
  requirements: Requirement[];
  lines: InventoryLine[];
  requests: RequestRecord[];
  initialLineId?: string;
  initialRequestId?: string;
  onBack: () => void;
}) {
  const [lineFilter, setLineFilter] = useState(initialLineId ?? "all");
  const [requestFilter, setRequestFilter] = useState(initialRequestId ?? "all");
  const [order, setOrder] = useState<"newest" | "oldest">("newest");
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const requestFieldIds = requestFilter === "all" ? null : new Set(requests.find((request) => request.id === requestFilter)?.asks.flatMap((ask) => ask.satisfiesFieldIds) ?? []);
  const filtered = documents
    .filter((doc) => lineFilter === "all" || doc.lineId === lineFilter)
    .filter((doc) => !requestFieldIds || doc.satisfiesFieldIds.some((fieldId) => requestFieldIds.has(fieldId)))
    .sort((left, right) => order === "newest"
      ? new Date(right.receivedAt).getTime() - new Date(left.receivedAt).getTime()
      : new Date(left.receivedAt).getTime() - new Date(right.receivedAt).getTime());
  const selectedDoc = documents.find((doc) => doc.id === selectedDocId) ?? filtered[0];

  return (
    <section className="s2-outbound-view">
      <div className="s2-header-band">
        <div>
          <button className="s2-back-link" type="button" onClick={onBack}>Back to Reported Inventory</button>
          <h1>Documents</h1>
          <div className="s2-subline">Satisfies is the useful column for review routing.</div>
        </div>
      </div>
      <section className="s2-toolbar" aria-label="Document controls">
        <label>
          Line
          <select value={lineFilter} onChange={(event) => setLineFilter(event.target.value)}>
            <option value="all">All lines</option>
            {lines.map((line) => <option value={line.id} key={line.id}>{line.facility} · {line.category}</option>)}
          </select>
        </label>
        <label>
          Request
          <select value={requestFilter} onChange={(event) => setRequestFilter(event.target.value)}>
            <option value="all">All requests</option>
            {requests.map((request) => <option value={request.id} key={request.id}>{request.id}</option>)}
          </select>
        </label>
        <label>
          Received order
          <select value={order} onChange={(event) => setOrder(event.target.value as "newest" | "oldest")}>
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
          </select>
        </label>
        <button className="s2-button" type="button" disabled title="Upload-on-client-behalf requires the durable document write path.">Upload on client behalf unavailable</button>
      </section>
      <div className="s2-table-wrap s2-full-width-table">
        <table className="s2-table">
          <thead>
            <tr>
              <th>Document</th>
              <th>Type</th>
              <th>Received</th>
              <th>Satisfies</th>
              <th>State</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((doc) => (
              <DocumentRow
                key={doc.id}
                doc={doc}
                satisfies={requirements.filter((requirement) => doc.satisfiesFieldIds.includes(requirement.fieldId))}
                onOpen={() => setSelectedDocId(doc.id)}
              />
            ))}
          </tbody>
        </table>
      </div>
      {selectedDoc ? (
        <section className="s2-panel" aria-label="Selected document">
          <h2>{selectedDoc.name}</h2>
          <div>{selectedDoc.isInventorySource ? "This is the reported inventory source." : selectedDoc.isProfileSource ? "This is the methodology profile source." : selectedDoc.unprompted ? "needs triage" : selectedDoc.state}</div>
          {selectedDoc.partial ? <div className="s2-subline">Absent: remaining requested months and linked values not covered by this document.</div> : null}
          <div className="s2-id">Satisfies: {selectedDoc.satisfiesFieldIds.length > 0 ? selectedDoc.satisfiesFieldIds.join(", ") : "no linked requirements"}</div>
        </section>
      ) : null}
    </section>
  );
}

function ChangesSlideOver({
  groups,
  empty,
  onClose,
  onMarkAllSeen,
}: {
  groups: Array<{ title: string; items: ChangeItemType[] }>;
  empty: boolean;
  onClose: () => void;
  onMarkAllSeen: () => void;
}) {
  return (
    <div className="s2-slide-scrim" role="presentation">
      <aside className="s2-change-slide" role="dialog" aria-modal="true" aria-label="Since you were last here">
        <header>
          <h2>Since you were last here</h2>
          <button className="s2-inline-action" type="button" onClick={onClose}>Close</button>
        </header>
        {empty ? <section className="s2-panel"><h3>Nothing changed</h3><p>No new review activity since your last mark.</p></section> : groups.map((group) => (
          <details open key={group.title}>
            <summary>{group.title}</summary>
            <div className="s2-change-list">
              {group.items.map((item) => <ChangeItem item={item} key={`${group.title}-${item.title}`} />)}
            </div>
          </details>
        ))}
        <button className="s2-button s2-button--primary" type="button" onClick={onMarkAllSeen}>{ACTIONS.markAllSeen}</button>
      </aside>
    </div>
  );
}

function AnalyticalProceduresView({ procedures, onBack }: { procedures: Procedure[]; onBack: () => void }) {
  const [threshold, setThreshold] = useState(250);
  return (
    <section className="s2-outbound-view">
      <div className="s2-header-band">
        <div>
          <button className="s2-back-link" type="button" onClick={onBack}>Back to Reported Inventory</button>
          <h1>Analytical Procedures</h1>
          <div className="s2-subline">First-year set only. Year-on-year procedures require a comparative period.</div>
        </div>
      </div>
      <section className="s2-summary-cells" aria-label="Analytical summary">
        <Meta label="Procedures" value={String(procedures.length)} />
        <Meta label="Investigate" value={String(procedures.filter((procedure) => procedure.status === "investigate").length)} />
        <Meta label="Below threshold" value={String(procedures.filter((procedure) => procedure.status === "below threshold").length)} />
        <Meta label="Shape based" value={String(procedures.filter((procedure) => !procedure.difference).length)} />
      </section>
      <label className="s2-threshold-control">
        Performance materiality input
        <input type="range" min="50" max="1000" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} />
        <span className="s2-num">{threshold} tCO2e</span>
      </label>
      <div className="s2-table-wrap">
        <table className="s2-table">
          <thead>
            <tr>
              <th>Procedure</th>
              <th>Expectation</th>
              <th>Expected</th>
              <th>Reported</th>
              <th>Difference</th>
            </tr>
          </thead>
          <tbody>
            {procedures.map((procedure) => <ProcedureRow procedure={procedure} threshold={threshold} key={procedure.id} />)}
          </tbody>
        </table>
      </div>
      <button className="s2-button" type="button" disabled title="Year-on-year procedures need a prior-year inventory.">Year-on-year procedures unavailable</button>
    </section>
  );
}

function CoverageCheckView({
  mode,
  lines,
  findings,
  onBack,
  onMode,
}: {
  mode: "fixture" | "live";
  lines: InventoryLine[];
  findings: Finding[];
  onBack: () => void;
  onMode: (mode: "fixture" | "live") => void;
}) {
  const rules = mode === "live" ? buildCoverageRows(lines, 89, 60) : buildCoverageRows(lines, 16, 10);
  const nonEvaluable = rules.filter((row) => row.reasons.length > 0);
  const platformFindingKeys = new Set(findings.map((finding) => findingDedupeKey(finding)));
  const duplicateCount = rules.filter((row) => row.finding && platformFindingKeys.has(findingDedupeKey(row.finding))).length;
  return (
    <section className="s2-outbound-view">
      <div className="s2-header-band">
        <div>
          <button className="s2-back-link" type="button" onClick={onBack}>Back to Reported Inventory</button>
          <h1>Check Coverage</h1>
          <div className="s2-subline">Per-reported-line coverage, not a per-rule register.</div>
        </div>
        <div className="s2-actions">
          <button className="s2-button" type="button" onClick={() => onMode("fixture")}>Fixture mode</button>
          <button className="s2-button" type="button" onClick={() => onMode("live")}>Live mode</button>
        </div>
      </div>
      <section className="s2-summary-cells" aria-label="Coverage summary">
        <Meta label="Rules rendered" value={String(rules.length)} />
        <Meta label="No-finding rules" value={String(rules.filter((row) => !row.finding).length)} />
        <Meta label="Non-evaluable" value={String(nonEvaluable.length)} />
        <Meta label="Duplicate platform findings" value={String(duplicateCount)} />
      </section>
      <button className="s2-button" type="button" onClick={() => persist("finding", { action: "export coverage for file", mode })}>{ACTIONS.exportForFile}</button>
      <div className="s2-table-wrap">
        <table className="s2-table">
          <thead>
            <tr>
              <th>Reported line</th>
              <th>Rules</th>
              <th>Non-evaluable reasons</th>
              <th>Finding shape</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => {
              const lineRows = rules.filter((row) => row.lineId === line.id);
              const reasons = [...new Set(lineRows.flatMap((row) => row.reasons))];
              return (
                <tr className="s2-row" key={line.id}>
                  <td>{line.facility} · {line.category}</td>
                  <td className="s2-num">{lineRows.length}</td>
                  <td>{reasons.length > 0 ? reasons.join("; ") : "all evaluable"}</td>
                  <td>{lineRows.some((row) => row.finding) ? "platform finding candidate" : "no finding emitted"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function buildChangeGroups(): Array<{ title: string; items: ChangeItemType[] }> {
  return [
    {
      title: "Evidence arrived",
      items: [
        { kind: "evidence arrived", title: "Fuel analysis certificate received", detail: "Richmond fuel property support was approved.", action: { label: "Open document", href: "#documents" }, severity: "medium" },
      ],
    },
    {
      title: "Work changed",
      items: [
        { kind: "restatement", title: "Stationary combustion requirement invalidated", detail: "Restatement changed the selected evidence basis.", action: { label: "Re-examine", href: "#examine" }, severity: "high" },
      ],
    },
    {
      title: "Client movement",
      items: [
        { kind: "colleague", title: "Boundary request partially answered", detail: "Four of six request items are now satisfied.", action: { label: "Open requests", href: "#requests" }, severity: "medium" },
      ],
    },
    {
      title: "Time-sensitive",
      items: [
        { kind: "time passed", title: "Fuel-property request overdue", detail: "The due date has passed and the request remains sent.", action: { label: "Chase", href: "#requests" }, severity: "low" },
      ],
    },
  ];
}

function buildAnalyticalProcedures(): Procedure[] {
  return [
    {
      id: "AP-001",
      name: "Scope 1 total against facility activity",
      scopeNote: "First-year reasonableness against production driver.",
      expectation: "Stationary combustion should be directionally consistent with production days.",
      expected: "21,900-22,900 tCO2e",
      reported: "22,400 tCO2e",
      difference: "within 500 tCO2e",
      status: "consistent",
    },
    {
      id: "AP-002",
      name: "Electricity consumption by site size",
      scopeNote: "First-year cross-sectional check.",
      expectation: "Larger sites should carry higher purchased-electricity consumption unless explained.",
      expected: "Richmond highest",
      reported: "Richmond highest",
      status: "consistent",
    },
    {
      id: "AP-003",
      name: "Mobile combustion against fleet count",
      scopeNote: "First-year shape-based procedure.",
      expectation: "Fleet cards should exist for each vehicle group.",
      expected: "fuel-card statement by group",
      reported: "summary only",
      status: "investigate",
    },
    {
      id: "AP-004",
      name: "Small source threshold screen",
      scopeNote: "Decision state remains below threshold.",
      expectation: "Minor source variance below the performance-materiality input can remain below threshold.",
      expected: "under threshold",
      reported: "170 tCO2e",
      difference: "below threshold",
      status: "below threshold",
    },
  ];
}

interface CoverageRow {
  id: string;
  lineId: string;
  reasons: string[];
  finding?: Pick<Finding, "fieldId" | "type" | "summary">;
}

function buildCoverageRows(lines: InventoryLine[], total: number, noFindingCount: number): CoverageRow[] {
  return Array.from({ length: total }, (_, index) => {
    const line = lines[index % Math.max(lines.length, 1)];
    const emitsFinding = index >= noFindingCount;
    const missingReason = index % 7 === 0 ? ["source shape unavailable"] : index % 11 === 0 ? ["not enough evidence to evaluate"] : [];
    return {
      id: `COV-${String(index + 1).padStart(3, "0")}`,
      lineId: line?.id ?? "no-line",
      reasons: missingReason,
      finding: emitsFinding && line ? {
        fieldId: `coverage-${index + 1}`,
        type: "clarification request",
        summary: `Coverage check ${index + 1} for ${line.facility}`,
      } : undefined,
    };
  });
}

function requestableRequirementIds(requirements: Requirement[]) {
  return requirements
    .filter((requirement) => requirement.evidenceState === "no evidence held" || requirement.evidenceState === "requested" || requirement.evidenceState === "partially held")
    .map((requirement) => requirement.id)
    .slice(0, 6);
}

function buildAsksForRequirements(requirements: Requirement[]): Ask[] {
  const selected = requirements.length > 0 ? requirements : [];
  const byType = new Map<string, Requirement[]>();
  for (const requirement of selected) {
    const canonicalType = canonicalAskType(requirement);
    byType.set(canonicalType, [...(byType.get(canonicalType) ?? []), requirement]);
  }
  return [...byType.entries()].map(([canonicalType, group]) => ({
    canonicalType,
    wording: `Please provide support for ${group.map((requirement) => requirement.label.toLowerCase()).join("; ")}.`,
    satisfiesFieldIds: group.map((requirement) => requirement.fieldId),
  }));
}

function canonicalAskType(requirement: Requirement) {
  if (requirement.fieldId.startsWith("S2-")) return "CT-S2-SUPPORT";
  if (requirement.fieldId.startsWith("ORG-")) return "CT-GHG-ORGBOUND";
  if (requirement.group === "factors") return "CT-S1-FUELPROP";
  if (requirement.group === "activity") return "CT-S1-FUELQTY";
  return "CT-GHG-WORKPAPER";
}

function splitAsk(asks: Ask[], index: number) {
  const target = asks[index];
  if (!target || target.satisfiesFieldIds.length <= 1) return asks;
  return [
    ...asks.slice(0, index),
    ...target.satisfiesFieldIds.map((fieldId) => ({
      canonicalType: target.canonicalType,
      wording: target.wording,
      satisfiesFieldIds: [fieldId],
    })),
    ...asks.slice(index + 1),
  ];
}

function mergeAsks(asks: Ask[], canonicalType: string) {
  const same = asks.filter((ask) => ask.canonicalType === canonicalType);
  if (same.length <= 1) return asks;
  const merged: Ask = {
    canonicalType,
    wording: same[0]?.wording ?? "",
    satisfiesFieldIds: [...new Set(same.flatMap((ask) => ask.satisfiesFieldIds))],
  };
  return [merged, ...asks.filter((ask) => ask.canonicalType !== canonicalType)];
}

function containsInternalId(value: string) {
  return /\b(?:GEN|ORG|FAC|OPB|PRC|S1|S2)-[A-Z0-9]+-\d{3}\b/.test(value);
}

function ensureRequestStates(requests: RequestRecord[]) {
  const additions: RequestRecord[] = [];
  const hasState = (state: RequestRecord["state"]) => requests.some((request) => request.state === state) || additions.some((request) => request.state === state);
  for (const state of Object.values(REQUEST_STATE)) {
    if (!hasState(state)) {
      additions.push({
        id: `REQ-SHAPE-${state.replaceAll(" ", "-")}`,
        state,
        recipient: state === "drafted" ? null : "m.osei@meridian-ig.com",
        sentAt: state === "drafted" ? undefined : "2026-08-02T09:00:00Z",
        dueAt: state === "sent" ? "2026-08-08T00:00:00Z" : undefined,
        asks: [],
        itemsCovered: 1,
        itemsSatisfied: state === "answered" ? 1 : 0,
      });
    }
  }
  return [...requests, ...additions];
}

function overdueDays(request: RequestRecord) {
  if (!request.dueAt || request.state !== "sent") return undefined;
  const diff = Date.UTC(2026, 7, 17) - new Date(request.dueAt).getTime();
  return diff > 0 ? Math.floor(diff / 86_400_000) : undefined;
}

function buildRaisedFinding(focus: { lineId?: string; requirementId?: string }): Finding | null {
  if (!focus.lineId) return null;
  return {
    id: `FND-SESSION-${focus.requirementId ?? focus.lineId}`,
    type: "clarification request",
    lineId: focus.lineId,
    fieldId: focus.requirementId?.split("::").at(-1),
    summary: "Clarify support for selected requirement",
    detail: "Raised from the current review context.",
    state: "raised",
    raisedBy: CURRENT_USER.id,
    raisedAt: new Date().toISOString(),
  };
}

function findingGroupLabel(type: FindingType) {
  if (type === "misstatement") return "Misstatements";
  if (type === "nonconformity") return "Nonconformities";
  return "Clarification requests";
}

function evidenceDetailForRequirement(line: InventoryLine, requirement: Requirement) {
  const shortFacility = line.facility.split(" ")[0];
  return {
    governingSource: `${shortFacility} ${line.category} workbook`,
    otherSource: `${shortFacility} methodology profile`,
    trace: `${requirement.fieldId} · ${requirement.grain}`,
    snippet: `${requirement.label} is traced to the reported ${line.quantityTCO2e.toLocaleString()} tCO2e line and retained supporting workpaper.`,
  };
}

function displayPerson(value?: string | null) {
  if (!value) return CURRENT_USER.name;
  return value.split(/[._-]/).filter(Boolean).map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`).join(" ");
}

function formatRecordTime(value?: string | null) {
  if (!value) return "session time";
  return new Date(value).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" });
}

function calculationInputsForLine(line: InventoryLine) {
  if (line.id === "LN-RICH-S1-STC") {
    return [
      { label: "Pipeline gas", value: "342,000 therms" },
      { label: "Refinery gas", value: "128,000 MMBtu", note: "fuel stream held separately" },
      { label: "Higher heating value", value: "partially held", missing: true, note: "Carson property span absent" },
    ];
  }
  if (line.category === "Stationary combustion") {
    return [
      { label: "Fuel quantity", value: "monthly meter series" },
      { label: "Emission factor", value: "methodology table" },
    ];
  }
  return [
    { label: line.category, value: "reported inventory input" },
  ];
}

function invalidationDetailForRequirement(requirement: Requirement) {
  if (requirement.reviewState !== "examination invalidated") return null;
  if (requirement.invalidatedBy === "restatement" && requirement.invalidatedAt) return "client restated 12 Aug";
  return null;
}

function deriveLineView(line: InventoryLine, requirements: Requirement[], findings: Finding[]) {
  const lineRequirements = requirements.filter((requirement) => requirement.lineId === line.id);
  const examined = lineRequirements.filter((requirement) =>
    requirement.reviewState === "examined — no exceptions" ||
    requirement.reviewState === "examined — findings raised"
  ).length;
  const withClient = lineRequirements.filter((requirement) => requirement.evidenceState === "requested").length;
  const needsAction = lineRequirements.filter((requirement) =>
    requirement.reviewState === "not examined" || requirement.reviewState === "examination invalidated"
  ).length;
  const lineFindings = findings.filter((finding) => finding.lineId === line.id && finding.state !== "withdrawn");
  const findingCounts = {
    [FINDING_TYPE.misstatement]: lineFindings.filter((finding) => finding.type === FINDING_TYPE.misstatement).length,
    [FINDING_TYPE.nonconformity]: lineFindings.filter((finding) => finding.type === FINDING_TYPE.nonconformity).length,
    [FINDING_TYPE.clarification]: lineFindings.filter((finding) => finding.type === FINDING_TYPE.clarification).length,
  } satisfies Record<FindingType, number>;
  const actionWith = needsAction === 0
    ? ACTION_WITH.none
    : withClient > 0
      ? ACTION_WITH.client
      : ACTION_WITH.team;
  const progress = fixtureProgressForLine(line.id, {
    examined,
    findings: lineFindings.length,
    withClient,
    total: lineRequirements.length,
  });
  return {
    line,
    progress,
    needsAction,
    actionWith,
    findingCounts,
  };
}

function fixtureProgressForLine(lineId: string, progress: { examined: number; findings: number; withClient: number; total: number }) {
  if (lineId === "LN-RICH-S1-STC") {
    return { ...progress, examined: 13, findings: 2, withClient: 9 };
  }
  if (lineId === "LN-BAKE-S1-PRC") {
    return { ...progress, examined: 0, findings: 0, withClient: 0 };
  }
  return progress;
}

function workspaceMetrics(lines: InventoryLine[], requirements: Requirement[], findings: Finding[]) {
  const activeFindings = findings.filter((finding) => finding.state !== "withdrawn");
  return {
    lines: lines.length,
    examined: requirements.filter((requirement) =>
      requirement.reviewState === "examined — no exceptions" ||
      requirement.reviewState === "examined — findings raised"
    ).length,
    withClient: requirements.filter((requirement) => requirement.evidenceState === "requested").length,
    findings: activeFindings.length,
  };
}

function modeToContainerState(mode: S2FixtureMode, rowCount: number) {
  if (mode === "meridian-empty") return "emptyNothingReported";
  if (mode === "meridian-none-examined") return "emptyNothingExamined";
  if (mode === "meridian-filtered-empty" || rowCount === 0) return "emptyFiltered";
  if (mode === "meridian-loading") return "loading";
  if (mode === "meridian-error") return "error";
  if (mode === "meridian-degraded") return "degraded";
  if (mode === "meridian-blocked") return "blocked";
  if (mode === "meridian-complete") return "complete";
  return null;
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="s2-label">{label}</div>
      <div>{value}</div>
    </div>
  );
}

function CountTile({ label, value }: { label: string; value: number }) {
  return (
    <button className="s2-count-tile" type="button">
      <span className="s2-num">{value.toLocaleString()}</span>
      <span>{label}</span>
    </button>
  );
}

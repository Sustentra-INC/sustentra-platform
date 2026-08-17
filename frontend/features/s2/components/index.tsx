import { useId, useState, type KeyboardEvent, type ReactNode } from "react";

import {
  ACTIONS,
  ACTION_WITH,
  CONTAINER,
  EVIDENCE_STATE,
  FINDING_STATE,
  FINDING_TYPE,
  REFUSALS,
  REQUEST_STATE,
  TECHNIQUES_LIMITED,
} from "../constants/copy";
import type {
  ActionWith,
  Ask,
  ChangeItem as ChangeItemType,
  DocumentRecord,
  EvidenceState,
  Finding,
  FindingState,
  FindingType,
  InventoryLine,
  Procedure,
  RequestRecord,
  Requirement,
  ReviewState,
} from "../types";
import { Truncate, UnknownValue, isOneOf } from "./componentUtils";

export type StateRole = "blocking" | "open" | "resolved" | "active" | "unverifiable" | "na";

export interface User {
  id: string;
  name: string;
}

const STATE_ROLES: StateRole[] = ["blocking", "open", "resolved", "active", "unverifiable", "na"];
const FINDING_TYPES = Object.values(FINDING_TYPE);
const FINDING_STATES = Object.values(FINDING_STATE);
const EVIDENCE_STATES = Object.values(EVIDENCE_STATE);
const REQUEST_STATES = Object.values(REQUEST_STATE);
const ACTION_WITH_VALUES = Object.values(ACTION_WITH);

export function StateChip({
  value,
  role,
  sub,
  onClick,
}: {
  value: string;
  role: StateRole;
  sub?: string;
  onClick?: () => void;
}) {
  if (!isOneOf(role, STATE_ROLES)) return <UnknownValue value={role} />;
  const label = sub ? `${value}, ${sub}` : value;
  const Element = onClick ? "button" : "span";
  return (
    <Element
      className={`s2-state-chip s2-state-chip--${role}`}
      role="status"
      aria-label={label}
      onClick={onClick}
      type={onClick ? "button" : undefined}
    >
      <Truncate>{value}</Truncate>
      {sub ? <span className="s2-state-chip__sub">{sub}</span> : null}
    </Element>
  );
}

export function ProgressBar({
  examined,
  findings,
  withClient,
  total,
}: {
  examined: number;
  findings: number;
  withClient: number;
  total: number;
}) {
  const parts = [
    examined > 0 ? `${examined} examined` : null,
    findings > 0 ? `${findings} findings` : null,
    withClient > 0 ? `${withClient} with client` : null,
  ].filter(Boolean);
  const label = parts.length > 0 ? parts.join(" · ") : "nothing started";
  const safeTotal = Math.max(total, 1);
  return (
    <div className="s2-progress" role="img" aria-label={label} title={label}>
      <div className="s2-progress__track">
        <span className="s2-progress__segment s2-progress__segment--examined" style={{ width: `${(examined / safeTotal) * 100}%` }} />
        <span className="s2-progress__segment s2-progress__segment--findings" style={{ width: `${(findings / safeTotal) * 100}%` }} />
        <span className="s2-progress__segment s2-progress__segment--client" style={{ width: `${(withClient / safeTotal) * 100}%` }} />
      </div>
      <span className="s2-progress__label">{label}</span>
    </div>
  );
}

export function InventoryLineRow({
  line,
  progress,
  outstanding,
  actionWith,
  findingCounts,
  assignedTo,
  onOpen,
  onAssign,
}: {
  line: InventoryLine;
  progress: { examined: number; findings: number; withClient: number; total: number };
  outstanding: number;
  actionWith: ActionWith;
  findingCounts: Record<FindingType, number>;
  assignedTo?: User;
  onOpen: () => void;
  onAssign: (user?: User) => void;
}) {
  const actionWithKnown = isOneOf(actionWith, ACTION_WITH_VALUES);
  return (
    <tr
      className="s2-row s2-inventory-line-row"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter") onOpen();
      }}
      aria-label={`${line.category}, ${line.facility}, scope ${line.scope}, ${line.quantityTCO2e} tonnes, ${progress.examined} of ${progress.total} examined`}
    >
      <td><Truncate>{`${line.facility} · Scope ${line.scope} · ${line.category}`}</Truncate></td>
      <td className={`s2-num ${line.quantityTCO2e === 0 ? "s2-muted" : ""}`}>{line.quantityTCO2e.toLocaleString()}</td>
      <td><ProgressBar {...progress} /></td>
      <td className="s2-num">{outstanding}</td>
      <td>{actionWithKnown ? actionWith : <UnknownValue value={actionWith} />}</td>
      <td className="s2-finding-dots" title={`${findingCounts["misstatement"]} misstatements · ${findingCounts["nonconformity"]} nonconformities · ${findingCounts["clarification request"]} clarification requests`}>
        <span>{findingCounts["misstatement"]}</span>
        <span>{findingCounts["nonconformity"]}</span>
        <span>{findingCounts["clarification request"]}</span>
      </td>
      <td onClick={(event) => event.stopPropagation()}>
        <PersonSlot
          user={assignedTo}
          label="Assigned to"
          onChange={onAssign}
        />
      </td>
    </tr>
  );
}

export function RequirementRow({
  requirement,
  findings,
  onOpen,
  onInlineAction,
}: {
  requirement: Requirement;
  findings: Finding[];
  onOpen: () => void;
  onInlineAction: (action: "request" | "unobtainable" | "byProcedure" | "chase" | "reExamine") => void;
}) {
  const evidenceKnown = isOneOf(requirement.evidenceState, EVIDENCE_STATES);
  const reviewKnown = isKnownReviewState(requirement.reviewState);
  const canOpen = requirement.evidenceState !== EVIDENCE_STATE.none;
  const invalidationDetail = invalidationDetailForRequirement(requirement);
  return (
    <tr
      className="s2-row s2-requirement-row"
      tabIndex={0}
      onClick={() => {
        if (canOpen) onOpen();
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" && canOpen) onOpen();
      }}
      aria-label={`${requirement.label}, ${requirement.evidenceState}, ${requirement.reviewState}, ${findings.length} findings`}
    >
      <td>
        <Truncate>{requirement.label}</Truncate>
        <div className="s2-id">{requirement.fieldId}</div>
      </td>
      <td>
        {evidenceKnown ? <span>{requirement.evidenceState}</span> : <UnknownValue value={requirement.evidenceState} />}
        {evidenceKnown ? <RequirementInlineActions evidenceState={requirement.evidenceState} reviewState={requirement.reviewState} onAction={onInlineAction} /> : null}
      </td>
      <td>
        {reviewKnown ? requirement.reviewState : <UnknownValue value={requirement.reviewState} />}
        {invalidationDetail ? <div className="s2-subline">{invalidationDetail}</div> : null}
      </td>
      <td>{findings.length === 0 ? <span className="s2-muted">0</span> : findings.length}</td>
      <td>{canOpen ? <button className="s2-inline-action" type="button" onClick={(event) => { event.stopPropagation(); onOpen(); }}>{ACTIONS.open}</button> : <span className="s2-muted">inline only</span>}</td>
    </tr>
  );
}

function invalidationDetailForRequirement(requirement: Requirement) {
  if (requirement.reviewState !== "examination invalidated") return null;
  if (requirement.invalidatedBy === "restatement" && requirement.invalidatedAt) return "client restated 12 Aug";
  return null;
}

export function CalculationStrip({
  inputs,
  result,
  unheldShare,
}: {
  inputs: Array<{ label: string; value: string; note?: string; missing?: boolean }>;
  result: { value: string; note?: string };
  unheldShare?: number;
}) {
  const calculationLabel = inputs.length === 0
    ? `Calculation result ${result.value}`
    : `${inputs.map((input) => `${input.label} ${input.value}`).join(" times ")} equals ${result.value}`;
  return (
    <figure className="s2-calculation-strip" aria-label={calculationLabel}>
      {inputs.length === 0 ? <CalculationCell label="Input" value="no calculation recorded" /> : inputs.map((input, index) => (
        <FragmentWithOperator key={input.label} operator={index === 0 ? null : "x"}>
          <CalculationCell {...input} />
        </FragmentWithOperator>
      ))}
      <span className="s2-calc-operator">=</span>
      <CalculationCell label="Reported figure" value={result.value} note={unheldShare ? `${unheldShare}% rests on an unheld property` : result.note} />
    </figure>
  );
}

function FragmentWithOperator({ operator, children }: { operator: string | null; children: ReactNode }) {
  return (
    <>
      {operator ? <span className="s2-calc-operator">{operator}</span> : null}
      {children}
    </>
  );
}

function CalculationCell({ label, value, note, missing }: { label: string; value: string; note?: string; missing?: boolean }) {
  return (
    <div className={`s2-calc-cell ${missing ? "s2-calc-cell--missing" : ""}`}>
      <div className="s2-label">{label}</div>
      <Truncate>{value}</Truncate>
      {note ? <div className="s2-subline">{note}</div> : null}
    </div>
  );
}

export function CoverageGrid({
  axis,
  rows,
  expected,
  heldCount,
}: {
  axis: { name: string; values: string[] };
  rows: Array<{ label: string; held: boolean[]; risk?: "cut-off" | "completeness" }>;
  expected: number;
  heldCount: number;
}) {
  const gridId = useId();
  const [activeCell, setActiveCell] = useState({ row: 0, column: 0 });
  const activeCellId = `${gridId}-cell-${activeCell.row}-${activeCell.column}`;
  if (!axis.name || axis.values.length === 0) {
    return <div className="s2-coverage-grid" role="status">{heldCount} of {expected} held. coverage shape unavailable for this grain</div>;
  }
  function moveCell(event: KeyboardEvent<HTMLDivElement>) {
    const next = { ...activeCell };
    if (event.key === "ArrowRight") next.column = Math.min(axis.values.length - 1, activeCell.column + 1);
    else if (event.key === "ArrowLeft") next.column = Math.max(0, activeCell.column - 1);
    else if (event.key === "ArrowDown") next.row = Math.min(rows.length - 1, activeCell.row + 1);
    else if (event.key === "ArrowUp") next.row = Math.max(0, activeCell.row - 1);
    else return;
    event.preventDefault();
    setActiveCell(next);
  }
  return (
    <div className="s2-coverage-grid" tabIndex={0} role="grid" aria-label={`${heldCount} of ${expected} held`} aria-activedescendant={activeCellId} onKeyDown={moveCell}>
      <div className="s2-coverage-grid__header">{axis.name}</div>
      {rows.map((row, rowIndex) => (
        <div className="s2-coverage-grid__row" role="row" key={row.label}>
          <span><Truncate>{row.label}</Truncate>{row.risk ? <span className="s2-subline">{row.risk}</span> : null}</span>
          {axis.values.map((value, index) => (
            <span
              className={`s2-coverage-grid__cell ${activeCell.row === rowIndex && activeCell.column === index ? "s2-coverage-grid__cell--active" : ""}`}
              id={`${gridId}-cell-${rowIndex}-${index}`}
              role="gridcell"
              title={`${value} - ${row.held[index] ? "held" : "not held"}`}
              key={value}
            >
              {row.held[index] ? "■" : "□"}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

export function TechniqueSelector({
  techniques = TECHNIQUES_LIMITED,
  selected,
  onChange,
}: {
  techniques?: readonly string[];
  selected: string[];
  onChange: (selected: string[]) => void;
}) {
  function toggle(technique: string) {
    if (!TECHNIQUES_LIMITED.includes(technique as (typeof TECHNIQUES_LIMITED)[number])) return;
    onChange(selected.includes(technique) ? selected.filter((item) => item !== technique) : [...selected, technique]);
  }
  return (
    <div className="s2-technique-selector" role="group" aria-label="Record the examination">
      {techniques.map((technique, index) => {
        const known = TECHNIQUES_LIMITED.includes(technique as (typeof TECHNIQUES_LIMITED)[number]);
        return known ? (
          <button
            className={`s2-technique ${selected.includes(technique) ? "s2-technique--selected" : ""}`}
            type="button"
            key={technique}
            aria-pressed={selected.includes(technique)}
            onClick={() => toggle(technique)}
            onKeyDown={(event) => {
              if (event.key === String(index + 1)) toggle(technique);
            }}
          >
            {technique}
          </button>
        ) : (
          <UnknownValue key={technique} value={technique} />
        );
      })}
    </div>
  );
}

export function ExaminationRecord({
  techniques = TECHNIQUES_LIMITED,
  selected,
  conclusion,
  note,
  performedBy,
  performedAt,
  assuranceLevel,
  onChange,
  onRecord,
}: {
  techniques?: readonly string[];
  selected: string[];
  conclusion?: "noExceptions" | FindingType;
  note?: string;
  performedBy?: User;
  performedAt?: string;
  assuranceLevel: "limited" | "reasonable";
  onChange: (patch: { selected?: string[]; conclusion?: "noExceptions" | FindingType; note?: string }) => void;
  onRecord: (next: boolean) => void;
}) {
  const refused = conclusion === "noExceptions" && selected.length === 0;
  return (
    <section className="s2-examination-record" aria-label="Record the examination">
      <TechniqueSelector techniques={techniques} selected={selected} onChange={(next) => onChange({ selected: next })} />
      <div className="s2-actions">
        <button type="button" className="s2-button" onClick={() => onChange({ conclusion: "noExceptions" })}>A - no exceptions</button>
        {FINDING_TYPES.map((type) => (
          <button type="button" className="s2-button" key={type} onClick={() => onChange({ conclusion: type })}>{type}</button>
        ))}
      </div>
      <textarea className="s2-textarea" value={note ?? ""} onChange={(event) => onChange({ note: event.target.value })} aria-label="Examination note" />
      <div className="s2-subline">{assuranceLevel === "reasonable" ? "reasonable assurance assertion rows unavailable in this build" : "limited assurance record"}</div>
      <div className="s2-subline">{performedBy?.name ?? "C. Yang"} · {performedAt ?? new Date().toLocaleString()}</div>
      {refused ? <div className="s2-inline-refusal">{REFUSALS.noTechnique}</div> : null}
      <div className="s2-actions">
        <button className="s2-button s2-button--primary" type="button" onClick={() => refused ? undefined : onRecord(true)}>{ACTIONS.recordNext}</button>
        <button className="s2-button" type="button" onClick={() => refused ? undefined : onRecord(false)}>{ACTIONS.recordStay}</button>
      </div>
    </section>
  );
}

export function PersonSlot({
  user,
  label,
  required = true,
  excludeUserIds = [],
  onChange,
}: {
  user?: User;
  label: "Performed by" | "Reviewed by" | "Assigned to";
  required?: boolean;
  excludeUserIds?: string[];
  onChange: (user?: User) => void;
}) {
  const excluded = user ? excludeUserIds.includes(user.id) : false;
  return (
    <button
      className={`s2-person-slot ${user ? "s2-person-slot--filled" : ""}`}
      type="button"
      title={excluded ? REFUSALS.reviewerSameAsPerformer : undefined}
      disabled={excluded}
      onClick={() => onChange(user ? undefined : { id: "user-cyang", name: "C. Yang" })}
      aria-label={`${label}: ${user?.name ?? "unassigned"}`}
    >
      <span className="s2-person-slot__avatar">{user ? user.name.slice(0, 1) : ""}</span>
      <Truncate>{user?.name ?? `${label}${required ? "" : " optional"}`}</Truncate>
    </button>
  );
}

export function FindingRow({
  finding,
  showLine,
  selected,
  onSelect,
  onAction,
}: {
  finding: Finding;
  showLine?: boolean;
  selected?: boolean;
  onSelect: (selected: boolean) => void;
  onAction: (action: "putToClient" | "withdraw" | "reconsider" | "chase") => void;
}) {
  const typeKnown = isOneOf(finding.type, FINDING_TYPES);
  const stateKnown = isOneOf(finding.state, FINDING_STATES);
  return (
    <tr
      className="s2-row s2-finding-row"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === " ") {
          event.preventDefault();
          onSelect(!selected);
        }
      }}
      aria-label={`${finding.type}, ${finding.summary}, ${finding.state}${finding.type === FINDING_TYPE.misstatement && finding.magnitude ? `, magnitude ${finding.magnitude} tonnes` : ""}`}
    >
      <td><input type="checkbox" checked={Boolean(selected)} onChange={(event) => onSelect(event.target.checked)} aria-label={`Select ${finding.summary}`} /></td>
      {showLine ? <td><Truncate>{finding.lineId}</Truncate></td> : null}
      <td>{typeKnown ? finding.type : <UnknownValue value={finding.type} />}</td>
      <td><Truncate>{finding.summary}</Truncate>{finding.criterion ? <div className="s2-subline">{finding.criterion}</div> : null}</td>
      <td>{finding.type === FINDING_TYPE.misstatement ? <Magnitude value={finding.magnitude} basis={finding.magnitudeBasis} /> : <span className="s2-muted">n/a</span>}</td>
      <td>{stateKnown ? <StateChip value={finding.state} role={findingRole(finding.state)} sub={finding.refusalReason ? `"${finding.refusalReason}"` : undefined} /> : <UnknownValue value={finding.state} />}</td>
      <td className="s2-actions">
        <button className="s2-inline-action" type="button" onClick={() => onAction("putToClient")}>{ACTIONS.putToClient}</button>
        <button className="s2-inline-action" type="button" onClick={() => onAction("withdraw")}>{ACTIONS.withdraw}</button>
        {finding.state === FINDING_STATE.withdrawn ? <button className="s2-inline-action" type="button" onClick={() => onAction("reconsider")}>Reconsider</button> : null}
        {finding.state === FINDING_STATE.putToClient || finding.state === FINDING_STATE.noResponse ? <button className="s2-inline-action" type="button" onClick={() => onAction("chase")}>{ACTIONS.chase}</button> : null}
      </td>
    </tr>
  );
}

export function Magnitude({ value, basis }: { value?: number; basis?: string }) {
  if (value === undefined || value === null) return <span className="s2-muted s2-italic">not quantifiable</span>;
  return (
    <span className="s2-magnitude">
      <span className="s2-num">{value.toLocaleString()}</span>
      {basis ? <span className="s2-subline">{basis}</span> : null}
    </span>
  );
}

export function AskCard({
  ask,
  satisfies,
  editable,
  onEdit,
  onSplit,
  onMerge,
}: {
  ask: Ask;
  satisfies: Requirement[];
  editable: boolean;
  onEdit: (wording: string) => void;
  onSplit: () => void;
  onMerge: (id: string) => void;
}) {
  const hasInternalId = /\b(?:GEN|ORG|FAC|S1|S2)-[A-Z0-9]+-\d{3}\b/.test(ask.wording);
  return (
    <article className="s2-ask-card" aria-label={`Ask: ${ask.canonicalType}. Satisfies ${satisfies.length} requirements.`}>
      <h3>{ask.canonicalType}</h3>
      <textarea
        className="s2-textarea"
        value={ask.wording}
        readOnly={!editable}
        onChange={(event) => onEdit(event.target.value)}
        aria-label={`Ask wording for ${ask.canonicalType}`}
      />
      {hasInternalId ? <div className="s2-inline-refusal">Remove internal identifiers before sending.</div> : null}
      <footer className="s2-ask-card__footer">
        <span className="s2-id">{ask.satisfiesFieldIds.join(", ")}</span>
        <button type="button" className="s2-inline-action" onClick={onSplit}>Split</button>
        <button type="button" className="s2-inline-action" onClick={() => onMerge(ask.canonicalType)}>Merge</button>
      </footer>
    </article>
  );
}

export function RequestRow({
  request,
  unblocks,
  overdueDays,
  onAction,
}: {
  request: RequestRecord;
  unblocks: number;
  overdueDays?: number;
  onAction: (action: "send" | "chase" | "withdraw" | "failSend") => void;
}) {
  const known = isOneOf(request.state, REQUEST_STATES);
  const age = request.sentAt ? daysSince(request.sentAt) : "-";
  return (
    <tr className="s2-row" tabIndex={0} aria-label={`${request.id}, ${request.state}, ${age} days, unblocks ${unblocks} requirements`}>
      <td><Truncate>{request.id}</Truncate></td>
      <td>{known ? <StateChip value={request.state} role={requestRole(request.state)} sub={overdueDays && request.state === REQUEST_STATE.sent ? `${overdueDays} days overdue` : undefined} /> : <UnknownValue value={request.state} />}</td>
      <td>{age}</td>
      <td className="s2-num">{unblocks}</td>
      <td className="s2-actions">
        {request.state === REQUEST_STATE.drafted ? <button type="button" className="s2-inline-action" onClick={() => onAction("send")}>Send draft</button> : null}
        {request.state === REQUEST_STATE.drafted ? <button type="button" className="s2-inline-action" onClick={() => onAction("failSend")}>Simulate failed send</button> : null}
        <button type="button" className="s2-inline-action" onClick={() => onAction("chase")}>{ACTIONS.chase}</button>
        <button type="button" className="s2-inline-action" onClick={() => onAction("withdraw")}>{ACTIONS.withdraw}</button>
      </td>
    </tr>
  );
}

export function DocumentRow({
  doc,
  satisfies,
  onOpen,
}: {
  doc: DocumentRecord;
  satisfies: Requirement[];
  onOpen: () => void;
}) {
  return (
    <tr className="s2-row" tabIndex={0} onClick={onOpen} onKeyDown={(event) => event.key === "Enter" ? onOpen() : undefined} aria-label={`${doc.name}, ${doc.canonicalType}, received ${doc.receivedAt}, satisfies ${satisfies.length}`}>
      <td><Truncate>{doc.name}</Truncate><div className="s2-id">{doc.id}</div></td>
      <td><Truncate>{doc.canonicalType}</Truncate></td>
      <td>{new Date(doc.receivedAt).toLocaleDateString()}</td>
      <td>
        {doc.isInventorySource ? <strong>the reported inventory</strong> : doc.isProfileSource ? <strong>the methodology profile</strong> : satisfies.length === 0 ? <span className="s2-open-text">no linked requirements</span> : `${satisfies.length} requirements`}
        {doc.partial ? <div className="s2-subline">partial record; still absent values remain</div> : null}
      </td>
      <td>{doc.unprompted ? "needs triage" : doc.state}</td>
    </tr>
  );
}

export function ProcedureRow({ procedure, threshold }: { procedure: Procedure; threshold: number }) {
  if (!procedure.expectation) return <tr className="s2-row"><td colSpan={5}><UnknownValue value="missing expectation" /></td></tr>;
  return (
    <tr className="s2-row" tabIndex={0} aria-label={`${procedure.name}. Expected ${procedure.expectation}. Reported ${procedure.reported}. ${procedure.status}.`}>
      <td><Truncate>{procedure.name}</Truncate><div className="s2-subline">{procedure.scopeNote}</div></td>
      <td><Truncate>{procedure.expectation}</Truncate></td>
      <td>{procedure.expected}</td>
      <td>{procedure.reported}</td>
      <td>
        {procedure.difference ?? <span className="s2-muted">-</span>}
        {!procedure.difference ? <div className="s2-subline">shape, not quantity</div> : null}
        <div className="s2-threshold" title={`threshold ${threshold}`} />
      </td>
    </tr>
  );
}

export function ChangeItem({ item }: { item: ChangeItemType }) {
  return (
    <article className="s2-change-item" tabIndex={0} onKeyDown={(event) => {
      if (event.key === "Enter" && item.action) window.location.hash = item.action.href;
    }} aria-label={`${item.title}. ${item.detail ?? ""}`}>
      <Truncate>{item.title}</Truncate>
      <div className="s2-subline"><Truncate>{item.detail ?? ""}</Truncate></div>
      {item.action ? <a className="s2-inline-action" href={item.action.href}>{item.action.label}</a> : null}
    </article>
  );
}

export type S2ContainerStateValue =
  | "populated"
  | "emptyNothingReported"
  | "emptyNothingExamined"
  | "emptyFiltered"
  | "loading"
  | "error"
  | "degraded"
  | "blocked"
  | "complete";

export function ContainerState({
  state,
  detail,
  onAction,
}: {
  state: S2ContainerStateValue;
  detail?: Record<string, unknown>;
  onAction?: () => void;
}) {
  if (state === "populated") return null;
  const content = containerStateContent(state, detail);
  if (!content) return <UnknownValue value={state} />;
  return (
    <section className={`s2-container-state s2-container-state--${state}`} role="status" aria-live="polite">
      <h2>{content.title}</h2>
      <p>{content.hint}</p>
      {state === "loading" ? <SkeletonRows /> : null}
      {content.action ? <button className="s2-button" type="button" onClick={onAction}>{content.action}</button> : null}
    </section>
  );
}

function RequirementInlineActions({
  evidenceState,
  reviewState,
  onAction,
}: {
  evidenceState: EvidenceState;
  reviewState: ReviewState;
  onAction: (action: "request" | "unobtainable" | "byProcedure" | "chase" | "reExamine") => void;
}) {
  if (evidenceState === EVIDENCE_STATE.none) {
    return (
      <div className="s2-inline-actions">
        <button className="s2-inline-action" type="button" onClick={(event) => { event.stopPropagation(); onAction("request"); }}>{ACTIONS.request}</button>
        <button className="s2-inline-action" type="button" onClick={(event) => { event.stopPropagation(); onAction("unobtainable"); }}>{ACTIONS.unobtainable}</button>
        <button className="s2-inline-action" type="button" onClick={(event) => { event.stopPropagation(); onAction("byProcedure"); }}>{ACTIONS.byProcedure}</button>
      </div>
    );
  }
  if (evidenceState === EVIDENCE_STATE.requested) {
    return <button className="s2-inline-action" type="button" onClick={(event) => { event.stopPropagation(); onAction("chase"); }}>{ACTIONS.chase}</button>;
  }
  if (reviewState === "examination invalidated") {
    return <button className="s2-inline-action" type="button" onClick={(event) => { event.stopPropagation(); onAction("reExamine"); }}>{ACTIONS.reExamine}</button>;
  }
  return null;
}

function isKnownReviewState(value: string): boolean {
  return [
    "not examined",
    "examination in progress",
    "examined — no exceptions",
    "examined — findings raised",
    "examination invalidated",
  ].includes(value);
}

function findingRole(state: FindingState): StateRole {
  if (state === FINDING_STATE.withdrawn || state === FINDING_STATE.satisfied || state === FINDING_STATE.corrected) return "resolved";
  if (state === FINDING_STATE.putToClient) return "active";
  if (state === FINDING_STATE.declined || state === FINDING_STATE.noResponse) return "blocking";
  return "open";
}

function requestRole(state: RequestRecord["state"]): StateRole {
  if (state === REQUEST_STATE.answered || state === REQUEST_STATE.withdrawn || state === REQUEST_STATE.superseded) return "resolved";
  if (state === REQUEST_STATE.sent || state === REQUEST_STATE.partial) return "active";
  return "open";
}

function daysSince(value: string): number {
  return Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 86_400_000));
}

function containerStateContent(state: S2ContainerStateValue, detail?: Record<string, unknown>) {
  const lines = Number(detail?.lines ?? 8);
  const total = String(detail?.total ?? "49,758");
  const at = String(detail?.at ?? "last successful run");
  const missing = Array.isArray(detail?.missing) ? detail.missing.join(", ") : String(detail?.missing ?? "two lines");
  const loaded = Number(detail?.loaded ?? 6);
  const map: Record<Exclude<S2ContainerStateValue, "populated">, { title: string; hint: string; action?: string }> = {
    emptyNothingReported: { title: CONTAINER.noInventory, hint: CONTAINER.noInventoryHint, action: "Request the inventory" },
    emptyNothingExamined: { title: CONTAINER.noneExamined(lines, total), hint: CONTAINER.noneExaminedHint, action: "Open largest line" },
    emptyFiltered: { title: CONTAINER.filteredNone, hint: CONTAINER.filteredNoneHint, action: ACTIONS.clearFilters },
    loading: { title: CONTAINER.loadingLabel, hint: "" },
    error: { title: CONTAINER.errorTitle, hint: CONTAINER.errorHint(at), action: "Open underlying artefact" },
    degraded: { title: CONTAINER.degraded(loaded), hint: CONTAINER.degradedHint(missing) },
    blocked: { title: CONTAINER.blocked, hint: CONTAINER.blockedHint },
    complete: { title: CONTAINER.complete, hint: CONTAINER.completeHint },
  };
  return map[state as Exclude<S2ContainerStateValue, "populated">];
}

function SkeletonRows() {
  return (
    <div className="s2-skeleton" aria-hidden="true">
      {Array.from({ length: 6 }, (_, index) => <div className="s2-skeleton-row" key={index} />)}
    </div>
  );
}

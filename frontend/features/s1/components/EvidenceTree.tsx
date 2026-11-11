"use client";

import { ChevronRight, PanelsTopLeft, Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  BLOCK_SUMMARY,
  BLOCK_UNASSIGNED,
  SUPPORTING_UNASSIGNED,
  getEvidenceTree,
  isSameLine,
  lineTitle,
  type CalculationLine,
  type EvidenceLineSetting,
  type EvidenceTree as EvidenceTreeData,
  type Placement,
  type TreeCategory,
  type TreeCounts,
  type TreeDocRow,
  type TreeLevel2,
  type TreeLineNode,
  type TreeScope,
} from "../api/evidenceTree";
import { userFacingApiError } from "../api/s1Backend";
import type { EngagementConfig } from "../types";
import { createAuditIntent, type AuditIntentAction, type SessionAuditEntry } from "../utils/auditIntent";
import { formatPeriod } from "../utils/formatPeriod";
import { ActionMenu } from "./ActionMenu";
import { ContainerStateSurface } from "./ContainerStateSurface";

/**
 * The Evidence page in backend mode: one tree, Scope > Category > fuel > calculation line, with the
 * summary documents and the unassigned ones above it. Every count comes from the backend (a facility
 * filter asks the backend for the filtered, recounted tree). A row folds open to what is under it;
 * what is open is kept by the app, so it survives a visit to a document or a schedule.
 */

export interface EvidenceTreeProps {
  engagement: EngagementConfig;
  /** Changes when the evidence changes (a read finished, a file arrived): the tree loads again. */
  reloadKey: string;
  /** The facility the tree is filtered to, or null for all. Kept by the app. */
  facilityId: string | null;
  onFacilityChange: (facilityId: string | null) => void;
  /** Ids of the open rows, or null to start from the default (scopes open). */
  openIds: string[] | null;
  onOpenIdsChange: (ids: string[]) => void;
  onOpenExtraction: (documentId: string) => void;
  onOpenSchedule: (lineKey: string) => void;
  onOpenSetup?: () => void;
  /** Saves one move of one placement; rejects with the reason when it did not save. */
  onMovePlacement: (documentId: string, move: Placement) => Promise<void>;
  /** Saves the reviewer-added lines (engagement setting `evidenceLines`); rejects when not saved. */
  onSaveLines: (lines: EvidenceLineSetting[]) => Promise<void>;
  onAudit: (intent: SessionAuditEntry) => void;
  /** Gives the app a chance to handle an ended session; true when it did. */
  onError?: (error: unknown) => boolean;
  writesEnabled: boolean;
}

type Dialog =
  | { kind: "move"; doc: TreeDocRow; from: string; section: string }
  | { kind: "newLine"; scope: string; category: string; level2: TreeLevel2 }
  | { kind: "newFuel"; scope: string; category: TreeCategory }
  | { kind: "rename"; line: CalculationLine }
  | { kind: "delete"; line: CalculationLine };

type OnError = ((error: unknown) => boolean) | undefined;

const isLineKey = (key: string) => !key.startsWith("block:") && !key.startsWith("supporting:");
const UNKNOWN_LINE_LABEL = "Unassigned supporting evidence (its line was deleted)";

export function EvidenceTree(props: EvidenceTreeProps) {
  const { engagement, reloadKey, facilityId, openIds, onOpenIdsChange, onError } = props;
  const engagementId = engagement.engagementId;
  const [tree, setTree] = useState<EvidenceTreeData | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [menuId, setMenuId] = useState<string | null>(null);
  // A filter opens every row once, so the matches show; the reviewer can still close any of them.
  const openAllOnLoad = useRef(false);

  useEffect(() => {
    let live = true;
    getEvidenceTree(engagementId, facilityId)
      .then((next) => {
        if (!live) return;
        setTree(next);
        setProblem(null);
        if (openAllOnLoad.current) {
          openAllOnLoad.current = false;
          onOpenIdsChange(collectIds(next));
        }
      })
      .catch((error: unknown) => {
        if (!live || onError?.(error)) return;
        setProblem(userFacingApiError(error));
      });
    return () => {
      live = false;
    };
    // The callbacks change every render of the app; the tree loads when these change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engagementId, facilityId, reloadKey, reload]);

  const lineMap = useMemo(() => new Map((tree?.lines ?? []).map((l) => [l.key, l])), [tree]);
  const filtered = facilityId !== null;

  if (problem) {
    return (
      <div className="s1-system-banner" role="alert">
        <strong>Couldn&apos;t load the evidence tree</strong>
        <span>{problem} </span>
        <button className="s1-button" type="button" onClick={() => setReload((n) => n + 1)}>
          Try again
        </button>
      </div>
    );
  }
  if (!tree) return <ContainerStateSurface state="loading" />;

  const open = new Set(openIds ?? defaultOpen(tree));
  const setOpen = (ids: Iterable<string>) => onOpenIdsChange([...ids]);
  const toggle = (id: string) => {
    const next = new Set(open);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setOpen(next);
  };
  const isOpen = (id: string) => open.has(id);
  /** With a facility filter, a row the server counted no documents for is left out. */
  const noneFor = (counts: TreeCounts | undefined) => filtered && counts !== undefined && counts.documents === 0;

  const { summary, unassigned, supporting } = tree.blocks;
  const visibleScopes = supporting.scopes.filter((s) => !noneFor(s.counts));
  const nothingShown =
    filtered && summary.length + unassigned.length + supporting.unassigned.length + visibleScopes.length === 0;

  function changeFacility(next: string | null) {
    openAllOnLoad.current = next !== null;
    props.onFacilityChange(next);
  }

  function audit(action: AuditIntentAction, what: { documentId?: string; lineLabel?: string; from: string | null; to: string | null }) {
    props.onAudit(
      createAuditIntent({ action, documentId: what.documentId ?? "", lineLabel: what.lineLabel, oldValue: what.from, newValue: what.to })
    );
  }

  function placeLabel(key: string): string {
    if (key === BLOCK_SUMMARY) return "Summary documents and workbook";
    if (key === BLOCK_UNASSIGNED) return "Unassigned documents";
    if (key === SUPPORTING_UNASSIGNED) return "Unassigned supporting evidence";
    const line = lineMap.get(key);
    return line ? lineTitle(line) : UNKNOWN_LINE_LABEL;
  }

  function docRow(doc: TreeDocRow, section: string) {
    const id = `${section}|${doc.document_id}`;
    const from = doc.placement_from ?? section;
    const period = doc.period_start && doc.period_end ? formatPeriod(doc.period_start, doc.period_end) : null;
    const also = doc.also_in.map((key) => lineMap.get(key)).filter((l): l is CalculationLine => Boolean(l));
    return (
      <div key={id} className="s1-et-doc">
        <button className="s1-doc-link" type="button" onClick={() => props.onOpenExtraction(doc.document_id)}>
          {doc.file_name}
        </button>
        <span className="s1-et-doc__meta">
          {period ? <span>{period}</span> : null}
          {doc.facility_name ? <span className="s1-chip">{doc.facility_name}</span> : null}
          {section === BLOCK_UNASSIGNED ? <span>{processingText(doc.processing_status)}</span> : null}
          {doc.flags.includes("unknown_line") ? <span>Its line was deleted</span> : null}
          {also.length ? <span>Also in {also.map(lineTitle).join(", ")}</span> : null}
        </span>
        <span className="s1-et-doc__vals">{doc.values ? `${doc.accepted} of ${doc.values} accepted` : "No values yet"}</span>
        <ActionMenu
          label={`Actions for ${doc.file_name}`}
          isOpen={menuId === id}
          onOpenChange={(o) => setMenuId(o ? id : null)}
          entries={[
            { label: "Open document", action: () => props.onOpenExtraction(doc.document_id) },
            { label: "Move to…", disabled: !props.writesEnabled, action: () => setDialog({ kind: "move", doc, from, section }) },
          ]}
        />
      </div>
    );
  }

  function docList(docs: TreeDocRow[], section: string) {
    return <div className="s1-et-docs">{docs.map((d) => docRow(d, section))}</div>;
  }

  function lineNode(node: TreeLineNode) {
    const { line } = node;
    const id = `line:${line.key}`;
    if (noneFor(node.counts)) return null;
    return (
      <Fold
        key={line.key}
        id={id}
        depth={4}
        open={isOpen(id)}
        onToggle={toggle}
        title={line.label}
        tag={line.created_by_user ? "Added by a reviewer" : undefined}
        counts={node.counts}
        actions={
          <>
            <button
              className="s1-icon-tile"
              type="button"
              aria-label={`Open supporting schedule for ${lineTitle(line)}`}
              title="Open supporting schedule"
              onClick={() => props.onOpenSchedule(line.key)}
            >
              <PanelsTopLeft aria-hidden />
            </button>
            {line.created_by_user && props.writesEnabled ? (
              <ActionMenu
                label={`Actions for ${lineTitle(line)}`}
                isOpen={menuId === id}
                onOpenChange={(o) => setMenuId(o ? id : null)}
                entries={[
                  { label: "Rename", action: () => setDialog({ kind: "rename", line }) },
                  { label: "Delete", action: () => setDialog({ kind: "delete", line }) },
                ]}
              />
            ) : null}
          </>
        }
      >
        {node.documents.length ? docList(node.documents, line.key) : <p className="s1-et-none">No documents on this line yet.</p>}
      </Fold>
    );
  }

  function level2Node(scope: string, category: TreeCategory, l2: TreeLevel2) {
    const id = `l2:${category.category}:${l2.level2}`;
    if (noneFor(l2.counts)) return null;
    return (
      <Fold key={id} id={id} depth={3} open={isOpen(id)} onToggle={toggle} title={l2.label} counts={l2.counts}>
        {l2.lines.map((n) => lineNode(n))}
        {props.writesEnabled && !filtered ? (
          <button className="s1-et-add" type="button" onClick={() => setDialog({ kind: "newLine", scope, category: category.category, level2: l2 })}>
            <Plus aria-hidden /> New calculation line in {l2.label}
          </button>
        ) : null}
      </Fold>
    );
  }

  function categoryNode(scope: TreeScope, category: TreeCategory) {
    const id = `cat:${scope.scope}:${category.category}`;
    if (noneFor(category.counts)) return null;
    return (
      <Fold key={id} id={id} depth={2} open={isOpen(id)} onToggle={toggle} title={category.label} counts={category.counts}>
        {category.level2s.map((l2) => level2Node(scope.scope, category, l2))}
        {props.writesEnabled && !filtered ? (
          <button className="s1-et-add" type="button" onClick={() => setDialog({ kind: "newFuel", scope: scope.scope, category })}>
            <Plus aria-hidden /> New fuel
          </button>
        ) : null}
      </Fold>
    );
  }

  const done = () => {
    setDialog(null);
    setReload((n) => n + 1);
  };

  return (
    <div className="s1-et">
      <div className="s1-et-bar">
        <label className="s1-et-facility">
          <span>Facility</span>
          <select value={facilityId ?? ""} onChange={(e) => changeFacility(e.target.value || null)} aria-label="Facility">
            <option value="">All facilities</option>
            {tree.facilities.map((f) => (
              <option key={f.facility_id} value={f.facility_id}>
                {f.name}
              </option>
            ))}
          </select>
        </label>
        <span className="s1-et-bar__fold">
          <button className="s1-linklike" type="button" onClick={() => setOpen(collectIds(tree))}>
            Expand all
          </button>
          <button className="s1-linklike" type="button" onClick={() => setOpen([])}>
            Collapse all
          </button>
        </span>
      </div>

      {nothingShown ? (
        <div className="s1-ws-empty" role="status">
          <p>No documents belong to this facility.</p>
          <button className="s1-button" type="button" onClick={() => changeFacility(null)}>
            Show all facilities
          </button>
        </div>
      ) : null}

      {!filtered || summary.length ? (
        <Fold
          id="b:summary"
          depth={0}
          open={isOpen("b:summary")}
          onToggle={toggle}
          title="Summary documents and workbook"
          tag="Company-prepared, not source evidence"
          counts={tree.blocks.summary_counts}
        >
          {summary.length ? docList(summary, BLOCK_SUMMARY) : <p className="s1-et-none">No summary documents yet.</p>}
        </Fold>
      ) : null}

      {!filtered || unassigned.length ? (
        <Fold
          id="b:unassigned"
          depth={0}
          open={isOpen("b:unassigned")}
          onToggle={toggle}
          title="Unassigned documents"
          subtitle="System could not identify these"
          counts={tree.blocks.unassigned_counts}
        >
          {unassigned.length ? docList(unassigned, BLOCK_UNASSIGNED) : <p className="s1-et-none">Nothing here.</p>}
        </Fold>
      ) : null}

      {!filtered || visibleScopes.length || supporting.unassigned.length ? (
        <Fold id="b:supporting" depth={0} open={isOpen("b:supporting")} onToggle={toggle} title="Supporting evidence">
          {visibleScopes.map((scope) => {
            const id = `scope:${scope.scope}`;
            return (
              <Fold key={id} id={id} depth={1} open={isOpen(id)} onToggle={toggle} title={scope.label} counts={scope.counts}>
                {scope.categories.map((c) => categoryNode(scope, c))}
              </Fold>
            );
          })}
          {!filtered || supporting.unassigned.length ? (
            <Fold
              id="b:supporting-unassigned"
              depth={1}
              open={isOpen("b:supporting-unassigned")}
              onToggle={toggle}
              title="Unassigned supporting evidence"
              counts={supporting.unassigned_counts}
            >
              {supporting.unassigned.length ? docList(supporting.unassigned, SUPPORTING_UNASSIGNED) : <p className="s1-et-none">Nothing here.</p>}
            </Fold>
          ) : null}
        </Fold>
      ) : null}

      {!filtered && tree.set_aside.length ? (
        <Fold id="b:set-aside" depth={0} open={isOpen("b:set-aside")} onToggle={toggle} title="Set aside" subtitle="Withdrawn, duplicate or replaced: not used in any line">
          <div className="s1-et-docs">
            {tree.set_aside.map((d) => (
              <div key={d.document_id} className="s1-et-doc">
                <button className="s1-doc-link" type="button" onClick={() => props.onOpenExtraction(d.document_id)}>
                  {d.file_name}
                </button>
                <span className="s1-et-doc__meta">{d.reason}</span>
              </div>
            ))}
          </div>
        </Fold>
      ) : null}

      {dialog?.kind === "move" ? (
        <MoveDialog
          tree={tree}
          doc={dialog.doc}
          from={dialog.from}
          section={dialog.section}
          lineMap={lineMap}
          placeLabel={placeLabel}
          onError={onError}
          onCancel={() => setDialog(null)}
          onMove={async (to) => {
            await props.onMovePlacement(dialog.doc.document_id, { from: dialog.from, to });
            audit("move_placement", { documentId: dialog.doc.document_id, from: placeLabel(dialog.from), to: placeLabel(to) });
            done();
          }}
        />
      ) : null}

      {dialog?.kind === "newLine" || dialog?.kind === "newFuel" ? (
        <NewLineDialog
          dialog={dialog}
          tree={tree}
          engagement={engagement}
          onOpenSetup={props.onOpenSetup}
          onError={onError}
          onCancel={() => setDialog(null)}
          onCreate={async (entry, isFuel) => {
            await props.onSaveLines([...(engagement.evidenceLines ?? []), entry]);
            audit(isFuel ? "create_fuel" : "create_line", { lineLabel: `${entry.level2_label} · ${entry.label}`, from: null, to: entry.label });
            done();
          }}
        />
      ) : null}

      {dialog?.kind === "rename" ? (
        <TextDialog
          title="Rename calculation line"
          label="Line name"
          initial={dialog.line.label}
          action="Rename"
          onError={onError}
          onCancel={() => setDialog(null)}
          onSubmit={async (name) => {
            const line = dialog.line;
            await props.onSaveLines((engagement.evidenceLines ?? []).map((l) => (isSameLine(l, line) ? { ...l, label: name } : l)));
            audit("rename_line", { lineLabel: lineTitle(line), from: line.label, to: name });
            done();
          }}
        />
      ) : null}

      {dialog?.kind === "delete" ? (
        <ConfirmDialog
          title={`Delete ${lineTitle(dialog.line)}?`}
          body="Its documents move to Unassigned supporting evidence. You can move them to another line from there."
          action="Delete line"
          onError={onError}
          onCancel={() => setDialog(null)}
          onConfirm={async () => {
            const line = dialog.line;
            await props.onSaveLines((engagement.evidenceLines ?? []).filter((l) => !isSameLine(l, line)));
            audit("delete_line", { lineLabel: lineTitle(line), from: line.label, to: null });
            done();
          }}
        />
      ) : null}
    </div>
  );
}

/* =============================== helpers =============================== */

function defaultOpen(tree: EvidenceTreeData): string[] {
  const ids = ["b:supporting", ...tree.blocks.supporting.scopes.map((s) => `scope:${s.scope}`)];
  if (tree.blocks.unassigned.length) ids.push("b:unassigned");
  return ids;
}

function collectIds(tree: EvidenceTreeData): string[] {
  const ids = ["b:summary", "b:unassigned", "b:supporting", "b:supporting-unassigned", "b:set-aside"];
  for (const scope of tree.blocks.supporting.scopes) {
    ids.push(`scope:${scope.scope}`);
    for (const category of scope.categories) {
      ids.push(`cat:${scope.scope}:${category.category}`);
      for (const l2 of category.level2s) {
        ids.push(`l2:${category.category}:${l2.level2}`);
        for (const l of l2.lines) ids.push(`line:${l.line.key}`);
      }
    }
  }
  return ids;
}

function processingText(status: string): string {
  const s = status.toLowerCase();
  if (s === "failed" || s === "blocked") return "Could not be read";
  if (s === "queued" || s === "processing" || s === "pending") return "Still reading";
  if (s === "unsupported") return "Not a supported file type";
  return "Needs a document type";
}

/* =============================== fold row =============================== */

function Fold({
  id,
  depth,
  open,
  onToggle,
  title,
  subtitle,
  tag,
  counts,
  actions,
  children,
}: {
  id: string;
  depth: number;
  open: boolean;
  onToggle: (id: string) => void;
  title: string;
  subtitle?: string;
  tag?: string;
  counts?: TreeCounts;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className={`s1-et-node s1-et-node--d${depth}${open ? " is-open" : ""}`}>
      <div className="s1-et-head">
        <button className="s1-et-toggle" type="button" aria-expanded={open} onClick={() => onToggle(id)}>
          <ChevronRight className="s1-et-caret" aria-hidden />
          <span className="s1-et-title">
            {title}
            {tag ? <span className="s1-chip">{tag}</span> : null}
            {subtitle ? <span className="s1-et-sub">{subtitle}</span> : null}
          </span>
        </button>
        {counts ? (
          <>
            <span className="s1-et-n">
              {counts.documents} {counts.documents === 1 ? "document" : "documents"}
            </span>
            <span className="s1-ws-gr__bar s1-et-bar-track" aria-hidden>
              <span className="s1-ws-gr__seg s1-ws-gr__seg--resolved" style={{ flexGrow: counts.accepted }} />
              <span className="s1-ws-gr__seg s1-ws-gr__seg--open" style={{ flexGrow: counts.to_review }} />
              <span className="s1-ws-gr__seg s1-ws-gr__seg--blocking" style={{ flexGrow: counts.issues }} />
            </span>
            <span
              className="s1-ws-gr__pct"
              title={`${counts.accepted} of ${counts.values} values accepted${counts.issues ? `, ${counts.issues} with issues` : ""}`}
            >
              {counts.pct_accepted}% accepted
            </span>
          </>
        ) : (
          <span className="s1-et-fill" />
        )}
        <span className="s1-et-actions">{actions}</span>
      </div>
      {open ? <div className="s1-et-body">{children}</div> : null}
    </section>
  );
}

/* =============================== dialogs =============================== */

/** A window that closes on Escape and puts the cursor in its first field. */
function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    box.current?.querySelector<HTMLElement>("input, select, textarea, button:not([disabled])")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="s1-modal-scrim">
      <div className="s1-modal" role="dialog" aria-modal="true" aria-label={title} ref={box}>
        <div className="s1-modal__head">
          <h2>{title}</h2>
        </div>
        {children}
      </div>
    </div>
  );
}

function useSubmit(onError: OnError) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await task();
    } catch (e) {
      setBusy(false);
      // An ended session signs the reviewer out; anything else is told in the window.
      if (onError?.(e)) return;
      setError(userFacingApiError(e));
    }
  }
  return { busy, error, run };
}

function MoveDialog({
  tree,
  doc,
  from,
  section,
  lineMap,
  placeLabel,
  onError,
  onCancel,
  onMove,
}: {
  tree: EvidenceTreeData;
  doc: TreeDocRow;
  from: string;
  /** Where the row sits now (a block, or its line). */
  section: string;
  lineMap: Map<string, CalculationLine>;
  placeLabel: (key: string) => string;
  onError: OnError;
  onCancel: () => void;
  onMove: (to: string) => Promise<void>;
}) {
  const [to, setTo] = useState("");
  const [confirming, setConfirming] = useState(false);
  const { busy, error, run } = useSubmit(onError);
  const here = new Set([from, section]);
  const groups = useMemo(() => {
    const scopeLabel = new Map(tree.blocks.supporting.scopes.map((s) => [s.scope, s.label]));
    const categoryLabel = new Map(tree.blocks.supporting.scopes.flatMap((s) => s.categories.map((c) => [c.category, c.label] as const)));
    const byGroup = new Map<string, CalculationLine[]>();
    for (const line of tree.lines) {
      if (line.key === from || line.key === section) continue;
      const name = `${scopeLabel.get(line.scope) ?? line.scope} › ${categoryLabel.get(line.category) ?? line.category}`;
      byGroup.set(name, [...(byGroup.get(name) ?? []), line]);
    }
    return [...byGroup.entries()];
  }, [tree, from, section]);
  const blocks = [
    { key: BLOCK_SUMMARY, label: "Summary documents and workbook" },
    { key: BLOCK_UNASSIGNED, label: "Unassigned documents" },
    { key: SUPPORTING_UNASSIGNED, label: "Unassigned supporting evidence" },
  ].filter((b) => !here.has(b.key));
  // Only a line that still exists has a calculation to change.
  const affected = [from, to].filter((k) => isLineKey(k) && lineMap.has(k)).map(placeLabel);
  const needsConfirm = affected.length > 0;

  return (
    <Dialog title="Move to…" onClose={onCancel}>
      <p className="s1-modal__note">
        Moves {doc.file_name} from {placeLabel(from)}. Only this placement moves; the document stays where else it is used.
      </p>
      <label className="s1-modal__field">
        <span>Move to</span>
        <select value={to} disabled={confirming || busy} onChange={(e) => setTo(e.target.value)} aria-label="Move to">
          <option value="">Choose where it goes</option>
          <optgroup label="Blocks">
            {blocks.map((b) => (
              <option key={b.key} value={b.key}>
                {b.label}
              </option>
            ))}
          </optgroup>
          {groups.map(([name, lines]) => (
            <optgroup key={name} label={name}>
              {lines.map((l) => (
                <option key={l.key} value={l.key}>
                  {lineTitle(l)}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      {confirming ? (
        <p className="s1-modal__note" role="alert">
          This changes the calculation for {affected.join(" and ")}.
        </p>
      ) : null}
      {error ? (
        <p className="s1-modal__note" role="alert">
          Not moved. {error}
        </p>
      ) : null}
      <div className="s1-modal__actions">
        <button
          className="s1-button s1-button--pri"
          type="button"
          disabled={!to || busy}
          onClick={() => {
            if (needsConfirm && !confirming) setConfirming(true);
            else void run(() => onMove(to));
          }}
        >
          {confirming ? "Confirm move" : "Move"}
        </button>
        <button className="s1-linklike" type="button" onClick={confirming ? () => setConfirming(false) : onCancel}>
          {confirming ? "Back" : "Cancel"}
        </button>
      </div>
    </Dialog>
  );
}

function NewLineDialog({
  dialog,
  tree,
  engagement,
  onOpenSetup,
  onError,
  onCancel,
  onCreate,
}: {
  dialog: Extract<Dialog, { kind: "newLine" | "newFuel" }>;
  tree: EvidenceTreeData;
  engagement: EngagementConfig;
  onOpenSetup?: () => void;
  onError: OnError;
  onCancel: () => void;
  onCreate: (entry: EvidenceLineSetting, isFuel: boolean) => Promise<void>;
}) {
  const isFuel = dialog.kind === "newFuel";
  const category = isFuel ? dialog.category.category : dialog.category;
  const { busy, error, run } = useSubmit(onError);
  const [fuel, setFuel] = useState("");
  const [anchor, setAnchor] = useState("");
  const [name, setName] = useState("");
  const company = category === "contractual";
  const mobile = category === "mobile";
  // Mobile lines sit on the vehicle groups from Setup (the server names their ids); the rest on facilities.
  const anchors = company
    ? [{ id: tree.anchors_for_contractual ?? "company", label: "Company-wide" }]
    : mobile
      ? (tree.vehicle_groups ?? []).map((g) => ({ id: g.anchor_id, label: g.label }))
      : engagement.facilities.map((f) => ({ id: f.facilityId, label: f.name }));
  const anchorKind = company ? "company" : mobile ? "vehicle_group" : "facility";
  const chosen = company ? anchors[0] : anchors.find((a) => a.id === anchor);
  const level2Label = isFuel ? fuel.trim() : dialog.level2.label;
  const ready = Boolean(chosen && level2Label);
  // A line this fuel already has at that anchor (a new fuel is checked by the server).
  const exists =
    ready && !isFuel && tree.lines.some((l) => l.category === category && l.level2 === dialog.level2.level2 && l.anchor_id === chosen!.id);
  const title = isFuel ? `New fuel in ${dialog.category.label}` : `New calculation line in ${dialog.level2.label}`;

  if (anchors.length === 0) {
    return (
      <Dialog title={title} onClose={onCancel}>
        <p className="s1-modal__note">
          {mobile ? "Add a vehicle group in Setup first. A line needs a vehicle group to sit on." : "Add a facility in Setup first. A line needs a facility to sit on."}
        </p>
        <div className="s1-modal__actions">
          {onOpenSetup ? (
            <button className="s1-button s1-button--pri" type="button" onClick={onOpenSetup}>
              Open Setup
            </button>
          ) : null}
          <button className="s1-linklike" type="button" onClick={onCancel}>
            Cancel
          </button>
        </div>
      </Dialog>
    );
  }

  return (
    <Dialog title={title} onClose={onCancel}>
      {isFuel ? (
        <label className="s1-modal__field">
          <span>Fuel name</span>
          <input className="s1-inline-input" value={fuel} onChange={(e) => setFuel(e.target.value)} />
        </label>
      ) : null}
      {company ? null : (
        <label className="s1-modal__field">
          <span>{mobile ? "Vehicle group" : "Facility"}</span>
          <select value={anchor} onChange={(e) => setAnchor(e.target.value)} aria-label={mobile ? "Vehicle group" : "Facility"}>
            <option value="">Choose one</option>
            {anchors.map((a) => (
              <option key={a.id} value={a.id}>
                {a.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="s1-modal__field">
        <span>Line name (optional)</span>
        <input className="s1-inline-input" value={name} placeholder={chosen?.label ?? ""} onChange={(e) => setName(e.target.value)} />
      </label>
      {exists ? (
        <p className="s1-modal__note" role="alert">
          That line already exists. Pick another {mobile ? "vehicle group" : "facility"}.
        </p>
      ) : null}
      {error ? (
        <p className="s1-modal__note" role="alert">
          Not saved. {error}
        </p>
      ) : null}
      <div className="s1-modal__actions">
        <button
          className="s1-button s1-button--pri"
          type="button"
          disabled={!ready || exists || busy}
          onClick={() =>
            void run(() =>
              onCreate(
                {
                  scope: dialog.scope,
                  category,
                  level2_label: level2Label,
                  anchor_kind: anchorKind,
                  anchor_id: chosen!.id,
                  label: name.trim() || chosen!.label,
                },
                isFuel
              )
            )
          }
        >
          {isFuel ? "Add fuel" : "Add line"}
        </button>
        <button className="s1-linklike" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </Dialog>
  );
}

function TextDialog({
  title,
  label,
  initial,
  action,
  onError,
  onCancel,
  onSubmit,
}: {
  title: string;
  label: string;
  initial: string;
  action: string;
  onError: OnError;
  onCancel: () => void;
  onSubmit: (value: string) => Promise<void>;
}) {
  const [value, setValue] = useState(initial);
  const { busy, error, run } = useSubmit(onError);
  const text = value.trim();
  return (
    <Dialog title={title} onClose={onCancel}>
      <label className="s1-modal__field">
        <span>{label}</span>
        <input className="s1-inline-input" value={value} maxLength={120} onChange={(e) => setValue(e.target.value)} />
      </label>
      {error ? (
        <p className="s1-modal__note" role="alert">
          Not saved. {error}
        </p>
      ) : null}
      <div className="s1-modal__actions">
        <button className="s1-button s1-button--pri" type="button" disabled={!text || text === initial || busy} onClick={() => void run(() => onSubmit(text))}>
          {action}
        </button>
        <button className="s1-linklike" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </Dialog>
  );
}

function ConfirmDialog({
  title,
  body,
  action,
  onError,
  onCancel,
  onConfirm,
}: {
  title: string;
  body: string;
  action: string;
  onError: OnError;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const { busy, error, run } = useSubmit(onError);
  return (
    <Dialog title={title} onClose={onCancel}>
      <p className="s1-modal__note">{body}</p>
      {error ? (
        <p className="s1-modal__note" role="alert">
          Not deleted. {error}
        </p>
      ) : null}
      <div className="s1-modal__actions">
        <button className="s1-button s1-button--pri" type="button" disabled={busy} onClick={() => void run(onConfirm)}>
          {action}
        </button>
        <button className="s1-linklike" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </Dialog>
  );
}

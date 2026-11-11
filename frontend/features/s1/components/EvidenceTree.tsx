"use client";

import { ChevronRight, PanelsTopLeft, Plus } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  BLOCK_SUMMARY,
  BLOCK_UNASSIGNED,
  SUPPORTING_UNASSIGNED,
  getEvidenceTree,
  isSameLine,
  slug,
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
 * summary documents and the unassigned ones above it. Every count comes from the backend. A row
 * folds open to what is under it; what is open is kept by the app, so it survives a visit to a
 * document or a schedule.
 */

export interface EvidenceTreeProps {
  engagement: EngagementConfig;
  /** Changes when the evidence changes (a read finished, a file arrived): the tree loads again. */
  reloadKey: string;
  /** Documents the page's filters let through; null when no filter is on. */
  visibleDocumentIds: Set<string> | null;
  onClearFilter: () => void;
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
  | { kind: "move"; doc: TreeDocRow; from: string }
  | { kind: "newLine"; scope: string; category: string; level2: TreeLevel2 }
  | { kind: "newFuel"; scope: string; category: TreeCategory }
  | { kind: "rename"; line: CalculationLine }
  | { kind: "delete"; line: CalculationLine };

const lineLabelOf = (line: CalculationLine) => `${line.level2_label} · ${line.label}`;
const isLineKey = (key: string) => !key.startsWith("block:") && !key.startsWith("supporting:");

export function EvidenceTree(props: EvidenceTreeProps) {
  const { engagement, reloadKey, visibleDocumentIds, openIds, onOpenIdsChange, onError } = props;
  const engagementId = engagement.engagementId;
  const [tree, setTree] = useState<EvidenceTreeData | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [menuId, setMenuId] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getEvidenceTree(engagementId)
      .then((next) => {
        if (!live) return;
        setTree(next);
        setProblem(null);
      })
      .catch((error: unknown) => {
        if (!live || onError?.(error)) return;
        setProblem(userFacingApiError(error));
      });
    return () => {
      live = false;
    };
    // onError changes every render of the app; the tree loads when the engagement or evidence changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engagementId, reloadKey, reload]);

  const lineMap = useMemo(() => new Map((tree?.lines ?? []).map((l) => [l.key, l])), [tree]);
  const filtered = visibleDocumentIds !== null;
  const seen = (doc: TreeDocRow) => !visibleDocumentIds || visibleDocumentIds.has(doc.document_id);

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
  const isOpen = (id: string) => filtered || open.has(id);

  const { summary, unassigned, supporting } = tree.blocks;
  const summaryDocs = summary.filter(seen);
  const unassignedDocs = unassigned.filter(seen);
  const supportingUnassigned = supporting.unassigned.filter(seen);
  const visibleScopes = supporting.scopes
    .map((scope) => ({ scope, categories: scope.categories.filter((c) => !filtered || categoryDocs(c).some(seen)) }))
    .filter((s) => !filtered || s.categories.length > 0);
  const nothingShown =
    filtered && summaryDocs.length + unassignedDocs.length + supportingUnassigned.length + visibleScopes.length === 0;

  function audit(action: AuditIntentAction, documentId: string, oldValue: string | null, newValue: string | null) {
    props.onAudit(createAuditIntent({ action, documentId, oldValue, newValue }));
  }

  function docRow(doc: TreeDocRow, from: string) {
    const id = `${from}|${doc.document_id}`;
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
          {from === BLOCK_UNASSIGNED ? <span>{processingText(doc.processing_status)}</span> : null}
          {doc.flags.includes("unknown_line") ? <span>Its line was deleted</span> : null}
          {also.length ? <span>Also in {also.map(lineLabelOf).join(", ")}</span> : null}
        </span>
        <span className="s1-et-doc__vals">
          {doc.values ? `${doc.accepted} of ${doc.values} accepted` : "No values yet"}
        </span>
        <ActionMenu
          label={`Actions for ${doc.file_name}`}
          isOpen={menuId === id}
          onOpenChange={(o) => setMenuId(o ? id : null)}
          entries={[
            { label: "Open document", action: () => props.onOpenExtraction(doc.document_id) },
            { label: "Move to…", disabled: !props.writesEnabled, action: () => setDialog({ kind: "move", doc, from: doc.placement_from ?? from }) },
          ]}
        />
      </div>
    );
  }

  function docList(docs: TreeDocRow[], from: string) {
    return <div className="s1-et-docs">{docs.map((d) => docRow(d, from))}</div>;
  }

  function lineNode(node: TreeLineNode) {
    const { line } = node;
    const id = `line:${line.key}`;
    const docs = node.documents.filter(seen);
    if (filtered && docs.length === 0) return null;
    return (
      <Fold
        key={line.key}
        id={id}
        depth={4}
        open={isOpen(id)}
        onToggle={toggle}
        title={line.label}
        tag={line.created_by_user ? "Added by a reviewer" : undefined}
        counts={countsFor(docs, node.counts, filtered)}
        actions={
          <>
            <button
              className="s1-icon-button"
              type="button"
              aria-label={`Open supporting schedule for ${lineLabelOf(line)}`}
              title="Open supporting schedule"
              onClick={() => props.onOpenSchedule(line.key)}
            >
              <PanelsTopLeft aria-hidden />
            </button>
            {line.created_by_user && props.writesEnabled ? (
              <ActionMenu
                label={`Actions for ${lineLabelOf(line)}`}
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
        {docs.length ? docList(docs, line.key) : <p className="s1-et-none">No documents on this line yet.</p>}
      </Fold>
    );
  }

  function level2Node(scope: string, category: TreeCategory, l2: TreeLevel2) {
    const id = `l2:${category.category}:${l2.level2}`;
    const docs = uniqueDocs(l2.lines.flatMap((l) => l.documents)).filter(seen);
    if (filtered && docs.length === 0) return null;
    return (
      <Fold
        key={id}
        id={id}
        depth={3}
        open={isOpen(id)}
        onToggle={toggle}
        title={l2.label}
        counts={countsFor(docs, l2.counts, filtered)}
      >
        {l2.lines.map((n) => lineNode(n))}
        {props.writesEnabled && !filtered ? (
          <button
            className="s1-et-add"
            type="button"
            onClick={() => setDialog({ kind: "newLine", scope, category: category.category, level2: l2 })}
          >
            <Plus aria-hidden /> New calculation line in {l2.label}
          </button>
        ) : null}
      </Fold>
    );
  }

  function categoryNode(scope: TreeScope, category: TreeCategory) {
    const id = `cat:${scope.scope}:${category.category}`;
    const docs = uniqueDocs(categoryDocs(category)).filter(seen);
    return (
      <Fold
        key={id}
        id={id}
        depth={2}
        open={isOpen(id)}
        onToggle={toggle}
        title={category.label}
        counts={countsFor(docs, category.counts, filtered)}
      >
        {category.level2s.map((l2) => level2Node(scope.scope, category, l2))}
        {props.writesEnabled && !filtered ? (
          <button className="s1-et-add" type="button" onClick={() => setDialog({ kind: "newFuel", scope: scope.scope, category })}>
            <Plus aria-hidden /> New fuel
          </button>
        ) : null}
      </Fold>
    );
  }

  const allIds = collectIds(tree);

  return (
    <div className="s1-et">
      <div className="s1-et-bar">
        <button className="s1-linklike" type="button" onClick={() => setOpen(allIds)}>
          Expand all
        </button>
        <button className="s1-linklike" type="button" onClick={() => setOpen([])}>
          Collapse all
        </button>
      </div>

      {nothingShown ? (
        <div className="s1-ws-empty" role="status">
          <p>No files match this filter.</p>
          <button className="s1-button" type="button" onClick={props.onClearFilter}>
            Clear filter
          </button>
        </div>
      ) : null}

      {!filtered || summaryDocs.length ? (
        <Fold
          id="b:summary"
          depth={0}
          open={isOpen("b:summary")}
          onToggle={toggle}
          title="Summary documents and workbook"
          tag="Company-prepared, not source evidence"
          counts={countsFor(summaryDocs, null, filtered, summary.length)}
        >
          {summaryDocs.length ? docList(summaryDocs, BLOCK_SUMMARY) : <p className="s1-et-none">No summary documents yet.</p>}
        </Fold>
      ) : null}

      {!filtered || unassignedDocs.length ? (
        <Fold
          id="b:unassigned"
          depth={0}
          open={isOpen("b:unassigned")}
          onToggle={toggle}
          title="Unassigned documents"
          subtitle="System could not identify these"
          counts={countsFor(unassignedDocs, null, filtered, unassigned.length)}
        >
          {unassignedDocs.length ? docList(unassignedDocs, BLOCK_UNASSIGNED) : <p className="s1-et-none">Nothing here.</p>}
        </Fold>
      ) : null}

      {!filtered || visibleScopes.length || supportingUnassigned.length ? (
        <Fold id="b:supporting" depth={0} open={isOpen("b:supporting")} onToggle={toggle} title="Supporting evidence">
          {visibleScopes.map(({ scope, categories }) => {
            const id = `scope:${scope.scope}`;
            const docs = uniqueDocs(categories.flatMap(categoryDocs)).filter(seen);
            const sum = sumCounts(categories.map((c) => c.counts));
            return (
              <Fold
                key={id}
                id={id}
                depth={1}
                open={isOpen(id)}
                onToggle={toggle}
                title={scope.label}
                counts={countsFor(docs, sum, filtered)}
              >
                {categories.map((c) => categoryNode(scope, c))}
              </Fold>
            );
          })}
          {!filtered || supportingUnassigned.length ? (
            <Fold
              id="b:supporting-unassigned"
              depth={1}
              open={isOpen("b:supporting-unassigned")}
              onToggle={toggle}
              title="Unassigned supporting evidence"
              counts={countsFor(supportingUnassigned, null, filtered, supporting.unassigned.length)}
            >
              {supportingUnassigned.length ? (
                docList(supportingUnassigned, SUPPORTING_UNASSIGNED)
              ) : (
                <p className="s1-et-none">Nothing here.</p>
              )}
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
          lineMap={lineMap}
          onCancel={() => setDialog(null)}
          onMove={async (to) => {
            await props.onMovePlacement(dialog.doc.document_id, { from: dialog.from, to });
            audit("move_placement", dialog.doc.document_id, placeLabel(dialog.from, lineMap), placeLabel(to, lineMap));
            setDialog(null);
            setReload((n) => n + 1);
          }}
        />
      ) : null}

      {dialog?.kind === "newLine" || dialog?.kind === "newFuel" ? (
        <NewLineDialog
          dialog={dialog}
          tree={tree}
          engagement={engagement}
          onOpenSetup={props.onOpenSetup}
          onCancel={() => setDialog(null)}
          onCreate={async (entry, isFuel) => {
            await props.onSaveLines([...(engagement.evidenceLines ?? []), entry]);
            audit(isFuel ? "create_fuel" : "create_line", `${entry.level2_label} · ${entry.label}`, null, entry.anchor_id);
            setDialog(null);
            setReload((n) => n + 1);
          }}
        />
      ) : null}

      {dialog?.kind === "rename" ? (
        <TextDialog
          title="Rename calculation line"
          label="Line name"
          initial={dialog.line.label}
          action="Rename"
          onCancel={() => setDialog(null)}
          onSubmit={async (name) => {
            const line = dialog.line;
            await props.onSaveLines((engagement.evidenceLines ?? []).map((l) => (isSameLine(l, line) ? { ...l, label: name } : l)));
            audit("rename_line", lineLabelOf(line), line.label, name);
            setDialog(null);
            setReload((n) => n + 1);
          }}
        />
      ) : null}

      {dialog?.kind === "delete" ? (
        <ConfirmDialog
          title={`Delete ${lineLabelOf(dialog.line)}?`}
          body="Its documents move to Unassigned supporting evidence. You can move them to another line from there."
          action="Delete line"
          onCancel={() => setDialog(null)}
          onConfirm={async () => {
            const line = dialog.line;
            await props.onSaveLines((engagement.evidenceLines ?? []).filter((l) => !isSameLine(l, line)));
            audit("delete_line", lineLabelOf(line), line.key, null);
            setDialog(null);
            setReload((n) => n + 1);
          }}
        />
      ) : null}
    </div>
  );
}

/* =============================== helpers =============================== */

function categoryDocs(category: TreeCategory): TreeDocRow[] {
  return category.level2s.flatMap((l2) => l2.lines.flatMap((l) => l.documents));
}

function uniqueDocs(docs: TreeDocRow[]): TreeDocRow[] {
  return [...new Map(docs.map((d) => [d.document_id, d])).values()];
}

function sumCounts(all: TreeCounts[]): TreeCounts {
  const total = { documents: 0, values: 0, accepted: 0, to_review: 0, issues: 0, pct_accepted: 0 };
  for (const c of all) {
    total.documents += c.documents;
    total.values += c.values;
    total.accepted += c.accepted;
    total.to_review += c.to_review;
    total.issues += c.issues;
  }
  total.pct_accepted = total.values === 0 ? 0 : total.accepted === total.values ? 100 : Math.floor((total.accepted / total.values) * 100);
  return total;
}

/** The backend's counts; while a filter is on, the counts of the documents it lets through. */
function countsFor(docs: TreeDocRow[], server: TreeCounts | null, filtered: boolean, total?: number): TreeCounts {
  if (server && !filtered) return server;
  const values = docs.reduce((n, d) => n + d.values, 0);
  const accepted = docs.reduce((n, d) => n + d.accepted, 0);
  return {
    documents: filtered ? docs.length : (total ?? docs.length),
    values,
    accepted,
    to_review: values - accepted,
    issues: 0,
    pct_accepted: values === 0 ? 0 : accepted === values ? 100 : Math.floor((accepted / values) * 100),
  };
}

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

function placeLabel(key: string, lines: Map<string, CalculationLine>): string {
  if (key === BLOCK_SUMMARY) return "Summary documents and workbook";
  if (key === BLOCK_UNASSIGNED) return "Unassigned documents";
  if (key === SUPPORTING_UNASSIGNED) return "Unassigned supporting evidence";
  const line = lines.get(key);
  return line ? lineLabelOf(line) : key;
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
              <span
                className="s1-ws-gr__seg s1-ws-gr__seg--na"
                style={{ flexGrow: Math.max(0, counts.values - counts.accepted - counts.to_review - counts.issues) }}
              />
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

function Dialog({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="s1-modal-scrim">
      <div className="s1-modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="s1-modal__head">
          <h2>{title}</h2>
        </div>
        {children}
      </div>
    </div>
  );
}

function useSubmit() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run(task: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await task();
    } catch (e) {
      setError(userFacingApiError(e));
      setBusy(false);
    }
  }
  return { busy, error, run };
}

function MoveDialog({
  tree,
  doc,
  from,
  lineMap,
  onCancel,
  onMove,
}: {
  tree: EvidenceTreeData;
  doc: TreeDocRow;
  from: string;
  lineMap: Map<string, CalculationLine>;
  onCancel: () => void;
  onMove: (to: string) => Promise<void>;
}) {
  const [to, setTo] = useState("");
  const [confirming, setConfirming] = useState(false);
  const { busy, error, run } = useSubmit();
  const groups = useMemo(() => {
    const scopeLabel = new Map(tree.blocks.supporting.scopes.map((s) => [s.scope, s.label]));
    const categoryLabel = new Map(tree.blocks.supporting.scopes.flatMap((s) => s.categories.map((c) => [c.category, c.label] as const)));
    const byGroup = new Map<string, CalculationLine[]>();
    for (const line of tree.lines) {
      if (line.key === from) continue;
      const name = `${scopeLabel.get(line.scope) ?? line.scope} › ${categoryLabel.get(line.category) ?? line.category}`;
      byGroup.set(name, [...(byGroup.get(name) ?? []), line]);
    }
    return [...byGroup.entries()];
  }, [tree, from]);
  const blocks = [
    { key: BLOCK_SUMMARY, label: "Summary documents and workbook" },
    { key: BLOCK_UNASSIGNED, label: "Unassigned documents" },
    { key: SUPPORTING_UNASSIGNED, label: "Unassigned supporting evidence" },
  ].filter((b) => b.key !== from);
  const affected = [from, to].filter(isLineKey).map((k) => placeLabel(k, lineMap));
  const needsConfirm = affected.length > 0;

  return (
    <Dialog title="Move to…">
      <p className="s1-modal__note">
        Moves {doc.file_name} from {placeLabel(from, lineMap)}. Only this placement moves; the document stays where else it is used.
      </p>
      <label className="s1-modal__field">
        <span>Move to</span>
        <select
          value={to}
          disabled={confirming || busy}
          onChange={(e) => setTo(e.target.value)}
          aria-label="Move to"
        >
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
                  {lineLabelOf(l)}
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
  onCancel,
  onCreate,
}: {
  dialog: Extract<Dialog, { kind: "newLine" | "newFuel" }>;
  tree: EvidenceTreeData;
  engagement: EngagementConfig;
  onOpenSetup?: () => void;
  onCancel: () => void;
  onCreate: (entry: EvidenceLineSetting, isFuel: boolean) => Promise<void>;
}) {
  const isFuel = dialog.kind === "newFuel";
  const category = isFuel ? dialog.category.category : dialog.category;
  const { busy, error, run } = useSubmit();
  const [fuel, setFuel] = useState("");
  const [anchor, setAnchor] = useState("");
  const [name, setName] = useState("");
  const company = category === "contractual";
  const mobile = category === "mobile";
  // Mobile lines sit on vehicle groups (the ones lines already exist for); the rest on Setup facilities.
  const anchors = company
    ? [{ id: "company", label: "Company-wide" }]
    : mobile
      ? [...new Map(tree.lines.filter((l) => l.anchor_kind === "vehicle_group").map((l) => [l.anchor_id, { id: l.anchor_id, label: l.label }])).values()]
      : engagement.facilities.map((f) => ({ id: f.facilityId, label: f.name }));
  const anchorKind = company ? "company" : mobile ? "vehicle_group" : "facility";
  const chosen = company ? anchors[0] : anchors.find((a) => a.id === anchor);
  const level2 = isFuel ? slug(fuel) : dialog.level2.level2;
  const level2Label = isFuel ? fuel.trim() : dialog.level2.label;
  const ready = Boolean(chosen && level2);
  // The server derives the key from these parts; a line that is already there is refused.
  const exists = ready && tree.lines.some((l) => l.category === category && l.level2 === level2 && l.anchor_id === chosen!.id);
  const title = isFuel ? `New fuel in ${dialog.category.label}` : `New calculation line in ${dialog.level2.label}`;

  if (anchors.length === 0) {
    return (
      <Dialog title={title}>
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
    <Dialog title={title}>
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
          That line already exists. Pick another {mobile ? "vehicle group" : company ? "name" : "facility"}.
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
  onCancel,
  onSubmit,
}: {
  title: string;
  label: string;
  initial: string;
  action: string;
  onCancel: () => void;
  onSubmit: (value: string) => Promise<void>;
}) {
  const [value, setValue] = useState(initial);
  const { busy, error, run } = useSubmit();
  const text = value.trim();
  return (
    <Dialog title={title}>
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
  onCancel,
  onConfirm,
}: {
  title: string;
  body: string;
  action: string;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const { busy, error, run } = useSubmit();
  return (
    <Dialog title={title}>
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

"use client";

import { ChevronRight, PanelsTopLeft, Plus } from "lucide-react";
import { useWindowedRows } from "../hooks/useWindowedRows";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";

import {
  BLOCK_SUMMARY,
  BLOCK_UNASSIGNED,
  SUPPORTING_UNASSIGNED,
  getEvidenceTree,
  lineTitle,
  type CalculationFamily,
  type CalculationLine,
  type EvidenceLineSetting,
  type EvidenceTab,
  type EvidenceTree as EvidenceTreeData,
  type Placement,
  type RereadChoice,
  type TreeCategory,
  type TreeCounts,
  type TreeDocRow,
  type TreeFolder,
  type TreeLevel2,
  type TreeLineNode,
  type TreeScope,
} from "../api/evidenceTree";
import { ApiError } from "../../../lib/api";
import { getMethodologyReview } from "../api/methodologyReview";
import { factsReadByDocument } from "../utils/methodologyFacts";
import { userFacingApiError } from "../api/s1Backend";
import type { EngagementConfig } from "../types";
import { addedByText, createdByText, formatPeriod } from "../utils/formatPeriod";
import { useAssignTask } from "../../tasks/AssignTaskContext";
import { ActionMenu } from "./ActionMenu";
import { AiFacilityNote } from "./AiFacilityNote";
import { ContainerStateSurface } from "./ContainerStateSurface";

/**
 * The Evidence page in backend mode: one tree, Scope > Category > fuel > calculation line, with the
 * summary documents and the unassigned ones above it. Every count comes from the backend (a facility
 * filter asks the backend for the filtered, recounted tree). A row folds open to what is under it;
 * what is open is kept by the app, so it survives a visit to a document or a schedule.
 */

/** A re-read the reviewer's move asked for, by document id: reading now, or failed (the document stays where it was moved). */
export interface RereadState {
  typeId: string;
  typeName: string;
  status: "reading" | "failed";
  message?: string;
}

export interface EvidenceTreeProps {
  engagement: EngagementConfig;
  /** Changes when the evidence changes (a read finished, a file arrived): the tree loads again. */
  reloadKey: string;
  /** The facility the tree is filtered to, or null for all. Kept by the app. */
  facilityId: string | null;
  onFacilityChange: (facilityId: string | null) => void;
  /** The selected tab, kept by the app like the open rows so it survives a visit to a document or a schedule.
   *  The facility filter belongs to the Supporting evidence tab only. Without it the tree keeps its own. */
  tab?: EvidenceTab;
  onTabChange?: (tab: EvidenceTab) => void;
  /** The "By calculation line / By document type" switch, shown on the filter row of the Supporting evidence tab. */
  viewSwitch?: ReactNode;
  /** Ids of the open rows, or null to start from the default (scopes open). */
  openIds: string[] | null;
  onOpenIdsChange: (ids: string[]) => void;
  onOpenExtraction: (documentId: string) => void;
  onOpenSchedule: (lineKey: string) => void;
  onOpenSetup?: () => void;
  /** Opens Methodology review, where the facts read from a summary document are and where it can be read. */
  onOpenMethodology?: () => void;
  /** Saves one move of one placement; rejects with the reason when it did not save. */
  onMovePlacement: (documentId: string, move: Placement, reread?: RereadChoice) => Promise<void>;
  /** The reviewer takes Claude's facility suggestion: places the document on that Setup facility (their own decision,
   *  audited on the server); rejects with the reason when it did not save. */
  onPlaceOnFacility?: (documentId: string, facilityId: string) => Promise<void>;
  /** The three line actions run on the server, each with its own audit event; they reject with the reason. */
  onCreateLine: (entry: EvidenceLineSetting) => Promise<void>;
  onRenameLine: (line: CalculationLine, label: string) => Promise<void>;
  /** Resolves with how many documents moved to Unassigned supporting evidence. */
  onDeleteLine: (line: CalculationLine) => Promise<number>;
  /** Fuel (Level 2) actions, each run by the server with its own audit event; they reject with the reason. A rename keeps
   *  the fuel's id, so its documents, lines and decisions stay attached. Without them (an older server) a fuel has no menu. */
  onRenameFuel?: (category: string, level2: string, name: string) => Promise<void>;
  /** Deletes a fuel the reviewers made, with its lines. Resolves with how many documents moved to Unassigned supporting evidence. */
  onDeleteFuel?: (category: string, level2: string) => Promise<number>;
  /** Re-reads that moves asked for, by document id. */
  rereads?: Record<string, RereadState>;
  /** Asks again for a re-read that failed (or whose wait was lost): the type to read it as comes from the row. */
  onRetryReread?: (documentId: string, typeId: string, typeName: string) => void;
  /** Block 1 folders (one level). Each runs on the server with its own audit event and rejects with the reason.
   *  Without them (an older server), Block 1 stays a flat list. */
  onCreateFolder?: (name: string) => Promise<void>;
  onRenameFolder?: (folder: TreeFolder, name: string) => Promise<void>;
  /** Resolves with how many documents went to the top of Block 1. */
  onDeleteFolder?: (folder: TreeFolder) => Promise<number>;
  /** Puts a Block 1 document in a folder, or out of it (null). */
  onSetDocumentFolder?: (documentId: string, folderId: string | null) => Promise<void>;
  /** Gives the app a chance to handle an ended session; true when it did. */
  onError?: (error: unknown) => boolean;
  writesEnabled: boolean;
}

type Dialog =
  | { kind: "move"; doc: TreeDocRow; from: string; section: string }
  | { kind: "newLine"; scope: string; category: string; level2: TreeLevel2 }
  | { kind: "newFuel"; scope: string; category: TreeCategory }
  | { kind: "rename"; line: CalculationLine }
  | { kind: "renameFuel"; category: TreeCategory; level2: TreeLevel2 }
  /** `documents` is how many documents are under the fuel in the whole tree; null when that is not known. */
  | { kind: "deleteFuel"; category: TreeCategory; level2: TreeLevel2; documents: number | null }
  | { kind: "newFolder" }
  | { kind: "renameFolder"; folder: TreeFolder }
  | { kind: "deleteFolder"; folder: TreeFolder }
  | { kind: "folderOf"; doc: TreeDocRow }
  /** `documents` is how many documents are on the line in the whole tree; null when that is not known. */
  | { kind: "delete"; line: CalculationLine; documents: number | null };

type OnError = ((error: unknown) => boolean) | undefined;

const isLineKey = (key: string) => !key.startsWith("block:") && !key.startsWith("supporting:");
const UNKNOWN_LINE_LABEL = "Unassigned supporting evidence (its line was deleted)";

const TABS: { id: EvidenceTab; label: string }[] = [
  { id: "summary", label: "Summary documents and workbook" },
  { id: "supporting", label: "Supporting evidence" },
];

/** The Evidence page's two top-level tabs, in the page's underline tab style. Arrow keys move between them (the tab
 *  follows focus); Home and End jump to the ends. */
export function EvidenceTabs({ tab, onTabChange }: { tab: EvidenceTab; onTabChange: (tab: EvidenceTab) => void }) {
  function onKey(e: ReactKeyboardEvent<HTMLDivElement>) {
    const at = TABS.findIndex((t) => t.id === tab);
    const to =
      e.key === "ArrowRight" || e.key === "ArrowDown" ? (at + 1) % TABS.length
      : e.key === "ArrowLeft" || e.key === "ArrowUp" ? (at - 1 + TABS.length) % TABS.length
      : e.key === "Home" ? 0
      : e.key === "End" ? TABS.length - 1
      : -1;
    if (to < 0) return;
    e.preventDefault();
    onTabChange(TABS[to].id);
    window.requestAnimationFrame(() => document.getElementById(`s1-et-tab-${TABS[to].id}`)?.focus());
  }
  return (
    <div className="s1-ws-factabs" role="tablist" aria-label="Evidence" onKeyDown={onKey}>
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          id={`s1-et-tab-${t.id}`}
          aria-selected={tab === t.id}
          aria-controls={`s1-et-panel-${t.id}`}
          tabIndex={tab === t.id ? 0 : -1}
          className={`s1-ws-factab${tab === t.id ? " is-on" : ""}`}
          onClick={() => onTabChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function EvidenceTree(props: EvidenceTreeProps) {
  const { engagement, reloadKey, openIds, onOpenIdsChange, onError } = props;
  const engagementId = engagement.engagementId;
  const [ownTab, setOwnTab] = useState<EvidenceTab>("supporting");
  const tab = props.tab ?? ownTab;
  const setTab = props.onTabChange ?? setOwnTab;
  // The facility filter applies to Supporting evidence only: Block 1 is never filtered.
  const facilityId = tab === "supporting" ? props.facilityId : null;
  const assign = useAssignTask();
  const [tree, setTree] = useState<EvidenceTreeData | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [menuId, setMenuId] = useState<string | null>(null);
  const [placing, setPlacing] = useState<string | null>(null);
  const [placeProblem, setPlaceProblem] = useState<{ documentId: string; message: string } | null>(null);
  // A filter opens every row once, so the matches show; the reviewer can still close any of them.
  const openAllOnLoad = useRef(false);
  // Facts Methodology review has read, by document. null: not known (loading, or the server did not answer).
  const [facts, setFacts] = useState<Map<string, number> | null>(null);

  useEffect(() => {
    let live = true;
    getMethodologyReview(engagementId)
      .then((data) => live && setFacts(factsReadByDocument(data)))
      .catch(() => live && setFacts(null));
    return () => {
      live = false;
    };
  }, [engagementId, reloadKey, reload]);

  // The whole tree (Block 1 and the "All facilities" view) and the tree of the one facility filtered to are each
  // kept until the evidence changes, so switching tabs with a filter set asks the server for nothing it already has
  // and shows no stale view. The facility stays in the app's state; only the Supporting evidence tab applies it.
  const cache = useRef<{ stamp: string; all?: EvidenceTreeData; facility?: { id: string; tree: EvidenceTreeData } }>({ stamp: "" });
  const shownFor = useRef<string | null>(null);
  useEffect(() => {
    const stamp = `${engagementId}|${reloadKey}|${reload}`;
    if (cache.current.stamp !== stamp) cache.current = { stamp };
    const have = facilityId === null ? cache.current.all : cache.current.facility?.id === facilityId ? cache.current.facility.tree : undefined;
    if (have) {
      shownFor.current = facilityId;
      setTree(have);
      setProblem(null);
      return;
    }
    // Nothing kept for this view: do not leave the other view (filtered or not) showing while it loads.
    if ((shownFor.current === null) !== (facilityId === null)) setTree(null);
    let live = true;
    getEvidenceTree(engagementId, facilityId)
      .then((next) => {
        if (!live) return;
        if (cache.current.stamp === stamp) {
          if (facilityId === null) cache.current.all = next;
          else cache.current.facility = { id: facilityId, tree: next };
        }
        shownFor.current = facilityId;
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
  // The labels the server already sends, for the full "Also in" path.
  const pathLabels = useMemo(() => {
    const scopes = new Map<string, string>();
    const categories = new Map<string, string>();
    for (const s of tree?.blocks.supporting.scopes ?? []) {
      scopes.set(s.scope, s.label);
      for (const c of s.categories) categories.set(c.category, c.label);
    }
    return { scopes, categories };
  }, [tree]);

  // While the tree loads, or cannot be read, the page still offers the view switch (the other grouping needs no tree).
  const bareBar = tab === "supporting" && props.viewSwitch ? <div className="s1-et-bar">{props.viewSwitch}</div> : null;
  if (problem) {
    return (
      <>
        {bareBar}
        <div className="s1-system-banner" role="alert">
          <strong>Couldn&apos;t load the evidence tree</strong>
          <span>{problem} </span>
          <button className="s1-button" type="button" onClick={() => setReload((n) => n + 1)}>
            Try again
          </button>
        </div>
      </>
    );
  }
  if (!tree) {
    return (
      <>
        {bareBar}
        <ContainerStateSurface state="loading" />
      </>
    );
  }

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
  const nothingShown = filtered && unassigned.length + supporting.unassigned.length + visibleScopes.length === 0;
  function changeFacility(next: string | null) {
    openAllOnLoad.current = next !== null;
    props.onFacilityChange(next);
  }

  function placeLabel(key: string): string {
    if (key === BLOCK_SUMMARY) return "Summary documents and workbook";
    if (key === BLOCK_UNASSIGNED) return "Unassigned documents";
    if (key === SUPPORTING_UNASSIGNED) return "Unassigned supporting evidence";
    const line = lineMap.get(key);
    return line ? lineTitle(line) : UNKNOWN_LINE_LABEL;
  }

  /** "Scope 2 › Purchased energy › Electricity › Kent Cannery"; today's short title when a label is missing. */
  function alsoInPath(line: CalculationLine): string {
    const scope = pathLabels.scopes.get(line.scope);
    const category = pathLabels.categories.get(line.category);
    if (!scope || !category || !line.level2_label || !line.label) return lineTitle(line);
    return [scope, category, line.level2_label, line.label].join(" › ");
  }

  /** The folders of Block 1; empty on an older server. */
  const folderList = tree.blocks.summary_folders ?? [];
  const foldersOn = tree.blocks.summary_folders !== undefined && Boolean(props.onCreateFolder);

  /** A summary document feeds no line, so it is read for Methodology review: how many facts that read found in it. */
  function docValues(doc: TreeDocRow, section: string): ReactNode {
    if (doc.values) return `${doc.accepted} of ${doc.values} accepted`;
    if (section !== BLOCK_SUMMARY || facts === null) return "No values yet";
    const n = facts.get(doc.document_id) ?? 0;
    const open = props.onOpenMethodology;
    if (n > 0) {
      return (
        <>
          {n} {n === 1 ? "fact" : "facts"} read
          {open ? (
            <>
              {" · "}
              <button className="s1-linklike" type="button" onClick={open} aria-label={`Open Methodology review for ${doc.file_name}`}>
                Open
              </button>
            </>
          ) : null}
        </>
      );
    }
    return (
      <>
        Not read yet
        {open ? (
          <>
            {" · "}
            <button className="s1-linklike" type="button" onClick={open} aria-label={`Read ${doc.file_name} with Sustentra's AI`}>
              Read
            </button>
          </>
        ) : null}
      </>
    );
  }

  function docRow(doc: TreeDocRow, section: string) {
    const id = `${section}|${doc.document_id}`;
    const from = doc.placement_from ?? section;
    const period = doc.period_start && doc.period_end ? formatPeriod(doc.period_start, doc.period_end) : null;
    // This session's own state wins; else what the server kept (so a reload still shows it, and the way to try again).
    const local = props.rereads?.[doc.document_id];
    const kept = doc.reread;
    const rereadStatus: RereadState | null =
      local ?? (kept ? { typeId: kept.canonical_type_id, typeName: kept.type_name, status: kept.status === "failed" ? "failed" : "reading", message: kept.error ?? undefined } : null);
    const also = doc.also_in.map((key) => lineMap.get(key)).filter((l): l is CalculationLine => Boolean(l));
    return (
      <div key={id} className={`s1-et-doc${section === BLOCK_SUMMARY ? " s1-et-doc--summary" : ""}`}>
        <button className="s1-doc-link" type="button" onClick={() => props.onOpenExtraction(doc.document_id)}>
          {doc.file_name}
        </button>
        <span className="s1-et-doc__meta">
          {period ? <span>{period}</span> : null}
          {/* Under a facility's own line the facility is already named by the line. */}
          {doc.facility_name && !(lineMap.get(section)?.facility_id && lineMap.get(section)?.facility_id === doc.facility_id) ? (
            <span className="s1-chip">{doc.facility_name}</span>
          ) : null}
          {doc.facility_note ? <span>{doc.facility_note}</span> : null}
          {doc.facility_suggestion ? (
            <AiFacilityNote
              facilityName={doc.facility_suggestion.facility_name}
              quote={doc.facility_suggestion.quote}
              where={doc.facility_suggestion.where}
              explanation={doc.facility_suggestion.explanation}
              onOpenDocument={props.onOpenExtraction}
              disabled={!props.writesEnabled || !props.onPlaceOnFacility || placing === doc.document_id}
              onPlace={() => void placeOnFacility(doc.document_id, doc.facility_suggestion!.facility_id)}
            />
          ) : null}
          {placeProblem?.documentId === doc.document_id ? (
            <span role="alert">
              Couldn&apos;t place the document. {placeProblem.message}
            </span>
          ) : null}
          {section === BLOCK_UNASSIGNED ? <span>{processingText(doc.processing_status)}</span> : null}
          {rereadStatus ? (
            rereadStatus.status === "failed" ? (
              <span role="alert">
                Couldn&apos;t re-read as {rereadStatus.typeName}.{rereadStatus.message ? ` ${rereadStatus.message}` : ""}{" "}
                {props.onRetryReread ? (
                  <button className="s1-linklike" type="button" onClick={() => props.onRetryReread!(doc.document_id, rereadStatus.typeId, rereadStatus.typeName)}>
                    Try again
                  </button>
                ) : null}
              </span>
            ) : (
              <span role="status">
                Re-reading as {rereadStatus.typeName}…
                {/* After a reload nothing in this session is waiting for the read: it can be asked for again. */}
                {!local && props.onRetryReread ? (
                  <>
                    {" "}
                    <button className="s1-linklike" type="button" onClick={() => props.onRetryReread!(doc.document_id, rereadStatus.typeId, rereadStatus.typeName)}>
                      Try again
                    </button>
                  </>
                ) : null}
              </span>
            )
          ) : null}
          {doc.flags.includes("unknown_line") ? <span>Its line was deleted</span> : null}
          {also.map((l) => (
            <span key={l.key} className="s1-et-also">
              Also in {alsoInPath(l)}
            </span>
          ))}
        </span>
        <span className="s1-et-doc__vals">{docValues(doc, section)}</span>
        <ActionMenu
          label={`Actions for ${doc.file_name}`}
          isOpen={menuId === id}
          onOpenChange={(o) => setMenuId(o ? id : null)}
          entries={[
            { label: "Open document", action: () => props.onOpenExtraction(doc.document_id) },
            ...(assign
              ? [{
                  label: "Assign to…",
                  action: () =>
                    assign({
                      kind: "Document",
                      label: doc.file_name,
                      target: { kind: "document", item_id: doc.document_id },
                      title: `Review ${doc.file_name}`,
                    }),
                }]
              : []),
            { label: "Move to…", disabled: !props.writesEnabled, action: () => setDialog({ kind: "move", doc, from, section }) },
            ...(section === BLOCK_SUMMARY && folderList.length > 0 && props.onSetDocumentFolder
              ? [{ label: "Move to folder…", disabled: !props.writesEnabled, action: () => setDialog({ kind: "folderOf", doc }) }]
              : []),
          ]}
        />
      </div>
    );
  }

  function docList(docs: TreeDocRow[], section: string) {
    // A group of more than 100 documents draws only the rows near the screen.
    return <WindowedDocs docs={docs} renderRow={(d) => docRow(d, section)} />;
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
        tag={line.created_by_user ? addedByText(line.created_by_name, line.created_at) : undefined}
        counts={node.counts}
        actions={
          <>
            <button
              className="s1-icon-tile"
              type="button"
              aria-label={`Open data point review for ${lineTitle(line)}`}
              title="Open data point review"
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
                  { label: "Delete", action: () => void openDelete(line, node.counts.documents) },
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
    const manage = props.writesEnabled && !filtered && props.onRenameFuel && props.onDeleteFuel;
    return (
      <Fold
        key={id}
        id={id}
        depth={3}
        open={isOpen(id)}
        onToggle={toggle}
        title={l2.label}
        tag={l2.created_by_user ? createdByText(l2.created_by_name, l2.created_at) : undefined}
        counts={l2.counts}
        actions={
          manage ? (
            <ActionMenu
              label={`Actions for ${l2.label}`}
              isOpen={menuId === id}
              onOpenChange={(o) => setMenuId(o ? id : null)}
              entries={[
                { label: "Rename", action: () => setDialog({ kind: "renameFuel", category, level2: l2 }) },
                {
                  label: "Delete",
                  action: () => openDeleteFuel(category, l2),
                  unavailable: l2.created_by_user ? undefined : "Created by the system from your Setup; can't be deleted.",
                },
              ]}
            />
          ) : undefined
        }
      >
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

  /** Block 1: its folders (one level) first, then the documents at its top. */
  function summaryBody() {
    const loose = summary.filter((d) => !d.folder_id);
    const shownFolders = [...folderList]
      .filter((f) => !filtered || summary.some((d) => d.folder_id === f.folder_id))
      .sort((a, b) => a.name.localeCompare(b.name));
    if (!summary.length && !shownFolders.length) return <p className="s1-et-none">No summary documents yet.</p>;
    return (
      <>
        {shownFolders.map((folder) => {
          const id = `folder:${folder.folder_id}`;
          const inside = summary.filter((d) => d.folder_id === folder.folder_id);
          return (
            <Fold
              key={id}
              id={id}
              depth={1}
              open={isOpen(id)}
              onToggle={toggle}
              title={folder.name}
              counts={{ documents: inside.length, values: 0, accepted: 0, to_review: 0, issues: 0, pct_accepted: 0 }}
              countOnly
              actions={
                props.writesEnabled && !filtered && props.onRenameFolder && props.onDeleteFolder ? (
                  <ActionMenu
                    label={`Actions for folder ${folder.name}`}
                    isOpen={menuId === id}
                    onOpenChange={(o) => setMenuId(o ? id : null)}
                    entries={[
                      { label: "Rename", action: () => setDialog({ kind: "renameFolder", folder }) },
                      { label: "Delete", action: () => setDialog({ kind: "deleteFolder", folder }) },
                    ]}
                  />
                ) : null
              }
            >
              {inside.length ? docList(inside, BLOCK_SUMMARY) : <p className="s1-et-none">This folder is empty.</p>}
            </Fold>
          );
        })}
        {loose.length ? docList(loose, BLOCK_SUMMARY) : null}
      </>
    );
  }

  const done = () => {
    setDialog(null);
    setReload((n) => n + 1);
  };

  /** "Place on <facility>": the reviewer's own decision. The tree loads again, so the row moves to its facility. */
  async function placeOnFacility(documentId: string, facilityId: string) {
    if (!props.onPlaceOnFacility) return;
    setPlacing(documentId);
    setPlaceProblem(null);
    try {
      await guard(() => props.onPlaceOnFacility!(documentId, facilityId));
      setReload((n) => n + 1);
    } catch (e) {
      if (props.onError?.(e)) return;
      setPlaceProblem({ documentId, message: userFacingApiError(e) });
    } finally {
      setPlacing(null);
    }
  }

  /** Runs one server action. When the server says the page was out of date (409: moved or changed by someone
   *  else; 404: the line is already gone), the tree loads again and the server's sentence is shown. */
  async function guard<T>(task: () => Promise<T>): Promise<T> {
    try {
      return await task();
    } catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.status === 404)) setReload((n) => n + 1);
      throw e;
    }
  }

  /** The delete window names how many documents move. With a facility filter on, the tree counts only that
   *  facility's documents, so the count is read from the whole tree. */
  function openDeleteFuel(category: TreeCategory, level2: TreeLevel2) {
    // The menu is offered without a facility filter, so the count on show is the count in the whole tree.
    setDialog({ kind: "deleteFuel", category, level2, documents: level2.counts.documents });
  }

  async function openDelete(line: CalculationLine, shown: number) {
    if (facilityId === null) {
      setDialog({ kind: "delete", line, documents: shown });
      return;
    }
    let documents: number | null = null;
    try {
      documents = lineDocuments(await getEvidenceTree(engagementId), line.key);
    } catch {
      // The window still opens, and says the line's documents move without a number.
    }
    setDialog({ kind: "delete", line, documents });
  }

  return (
    <div className="s1-et">
      <div className="s1-et-bar">
        {tab === "supporting" ? (
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
        ) : null}
        {tab === "supporting" ? props.viewSwitch : null}
        <span className="s1-et-bar__fold">
          <button className="s1-linklike" type="button" onClick={() => setOpen(collectIds(tree))}>
            Expand all
          </button>
          <button className="s1-linklike" type="button" onClick={() => setOpen([])}>
            Collapse all
          </button>
        </span>
      </div>

      <div className={`s1-et s1-et-panel s1-et-panel--${tab}`} role="tabpanel" id={`s1-et-panel-${tab}`} aria-labelledby={`s1-et-tab-${tab}`}>
      {nothingShown ? (
        <div className="s1-ws-empty" role="status">
          <p>No documents belong to this facility.</p>
          <button className="s1-button" type="button" onClick={() => changeFacility(null)}>
            Show all facilities
          </button>
        </div>
      ) : null}

      {tab === "summary" ? (
        <Fold
          id="b:summary"
          depth={0}
          open={isOpen("b:summary")}
          onToggle={toggle}
          title="Summary documents and workbook"
          tag="Company-prepared, not source evidence"
          counts={tree.blocks.summary_counts}
          countOnly
        >
          {summaryBody()}
          {foldersOn && props.writesEnabled && !filtered ? (
            <button className="s1-et-add" type="button" onClick={() => setDialog({ kind: "newFolder" })}>
              <Plus aria-hidden /> New folder
            </button>
          ) : null}
        </Fold>
      ) : null}

      {tab === "supporting" ? (
        <>
          {tree.facilities.length === 0 ? (
            <p className="s1-et-none s1-et-nofac">
              No calculation lines yet. Add your facilities in Setup and each fuel gets one line per facility.{" "}
              {props.onOpenSetup ? (
                <button className="s1-linklike" type="button" onClick={props.onOpenSetup}>
                  Open Setup
                </button>
              ) : null}
            </p>
          ) : null}
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
              subtitle="Not yet on a calculation line"
              counts={supporting.unassigned_counts}
            >
              {supporting.unassigned.length ? docList(supporting.unassigned, SUPPORTING_UNASSIGNED) : <p className="s1-et-none">Nothing here.</p>}
            </Fold>
          ) : null}
        </>
      ) : null}

      {/* Block 2 shows on both tabs: what the system could not identify has no known type. */}
      {!filtered || unassigned.length ? (
        <Fold
          id="b:unassigned"
          depth={0}
          open={isOpen("b:unassigned")}
          onToggle={toggle}
          title="Unassigned documents"
          subtitle="System could not identify these"
          counts={tree.blocks.unassigned_counts}
          countOnly
        >
          {unassigned.length ? docList(unassigned, BLOCK_UNASSIGNED) : <p className="s1-et-none">Nothing here.</p>}
        </Fold>
      ) : null}

      {/* Set aside is of either kind of document, so it shows on both tabs, last. */}
      {tree.set_aside.length ? (
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
      </div>

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
          onMove={async (to, reread) => {
            // The server refuses a move from a place the document is no longer in (409), saving nothing.
            await guard(() =>
              reread
                ? props.onMovePlacement(dialog.doc.document_id, { from: dialog.from, to }, reread)
                : props.onMovePlacement(dialog.doc.document_id, { from: dialog.from, to })
            );
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
          onCreate={async (entry) => {
            await guard(() => props.onCreateLine(entry));
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
            await guard(() => props.onRenameLine(dialog.line, name));
            done();
          }}
        />
      ) : null}

      {dialog?.kind === "renameFuel" ? (
        <TextDialog
          title="Rename fuel"
          label="Fuel name"
          initial={dialog.level2.label}
          action="Rename"
          maxLength={80}
          check={(name) =>
            dialog.category.level2s.some((l) => l.level2 !== dialog.level2.level2 && l.label.trim().toLowerCase() === name.toLowerCase())
              ? `${name} already exists in ${dialog.category.label}.`
              : null
          }
          onError={onError}
          onCancel={() => setDialog(null)}
          onSubmit={async (name) => {
            await guard(() => props.onRenameFuel!(dialog.category.category, dialog.level2.level2, name));
            done();
          }}
        />
      ) : null}

      {dialog?.kind === "deleteFuel" ? (
        <ConfirmDialog
          title={`Delete ${dialog.level2.label}?`}
          body={
            dialog.documents === 0
              ? "It has no documents. Its calculation lines are deleted with it."
              : dialog.documents === 1
                ? "Its 1 document moves to Unassigned supporting evidence. Its value stops counting until you place it again."
                : dialog.documents === null
                  ? "Its documents move to Unassigned supporting evidence. Their values stop counting until you place them again."
                  : `Its ${dialog.documents} documents move to Unassigned supporting evidence. Their values stop counting until you place them again.`
          }
          action="Delete fuel"
          onError={onError}
          onCancel={() => setDialog(null)}
          onConfirm={async () => {
            await guard(() => props.onDeleteFuel!(dialog.category.category, dialog.level2.level2));
            done();
          }}
        />
      ) : null}

      {dialog?.kind === "newFolder" ? (
        <TextDialog
          title="New folder"
          label="Folder name"
          initial=""
          action="Create folder"
          onError={onError}
          onCancel={() => setDialog(null)}
          onSubmit={async (name) => {
            await guard(() => props.onCreateFolder!(name));
            done();
          }}
        />
      ) : null}

      {dialog?.kind === "renameFolder" ? (
        <TextDialog
          title="Rename folder"
          label="Folder name"
          initial={dialog.folder.name}
          action="Rename"
          onError={onError}
          onCancel={() => setDialog(null)}
          onSubmit={async (name) => {
            await guard(() => props.onRenameFolder!(dialog.folder, name));
            done();
          }}
        />
      ) : null}

      {dialog?.kind === "deleteFolder" ? (
        <ConfirmDialog
          title={`Delete folder ${dialog.folder.name}?`}
          body={
            dialog.folder.documents === 0
              ? "The folder is empty."
              : dialog.folder.documents === 1
                ? "Its 1 document is not deleted. It moves to the top of Summary documents and workbook."
                : `Its ${dialog.folder.documents} documents are not deleted. They move to the top of Summary documents and workbook.`
          }
          action="Delete folder"
          onError={onError}
          onCancel={() => setDialog(null)}
          onConfirm={async () => {
            await guard(() => props.onDeleteFolder!(dialog.folder));
            done();
          }}
        />
      ) : null}

      {dialog?.kind === "folderOf" ? (
        <FolderMoveDialog
          doc={dialog.doc}
          folders={folderList}
          onError={onError}
          onCancel={() => setDialog(null)}
          onMove={async (folderId) => {
            await guard(() => props.onSetDocumentFolder!(dialog.doc.document_id, folderId));
            done();
          }}
        />
      ) : null}

      {dialog?.kind === "delete" ? (
        <ConfirmDialog
          title={`Delete ${lineTitle(dialog.line)}?`}
          body={
            dialog.documents === null
              ? "Its documents move to Unassigned supporting evidence. You can move them to another line from there."
              : dialog.documents === 1
              ? "Its 1 document moves to Unassigned supporting evidence. You can move it to another line from there."
              : dialog.documents > 1
                ? `Its ${dialog.documents} documents move to Unassigned supporting evidence. You can move them to another line from there.`
                : "No documents are on this line."
          }
          action="Delete line"
          onError={onError}
          onCancel={() => setDialog(null)}
          onConfirm={async () => {
            await guard(() => props.onDeleteLine(dialog.line));
            done();
          }}
        />
      ) : null}
    </div>
  );
}

/* =============================== helpers =============================== */

/** "97% accepted", not "97.1%": whole percents read faster in a tree. Never rounds up to 100. */
function wholePercent(pct: number): number {
  return pct >= 100 ? 100 : Math.floor(pct);
}

function defaultOpen(tree: EvidenceTreeData): string[] {
  const ids = ["b:summary", "b:supporting", ...tree.blocks.supporting.scopes.map((s) => `scope:${s.scope}`)];
  if (tree.blocks.unassigned.length) ids.push("b:unassigned");
  // As in Claire's design, the first category with documents opens down to its calculation
  // lines, so the reviewer sees the lines and their supporting-schedule buttons on arrival.
  for (const scope of tree.blocks.supporting.scopes) {
    const category = scope.categories.find((c) => (c.counts?.documents ?? 1) > 0);
    if (!category) continue;
    ids.push(`cat:${scope.scope}:${category.category}`);
    const level2 = category.level2s.find((l) => (l.counts?.documents ?? 1) > 0);
    if (level2) ids.push(`l2:${category.category}:${level2.level2}`);
    break;
  }
  return ids;
}

function collectIds(tree: EvidenceTreeData): string[] {
  const ids = ["b:summary", "b:unassigned", "b:supporting", "b:supporting-unassigned", "b:set-aside"];
  for (const folder of tree.blocks.summary_folders ?? []) ids.push(`folder:${folder.folder_id}`);
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

/** How many documents are on a line in this tree (0 when the line is not in it). */
function lineDocuments(tree: EvidenceTreeData, lineKey: string): number {
  for (const scope of tree.blocks.supporting.scopes) {
    for (const category of scope.categories) {
      for (const l2 of category.level2s) {
        const node = l2.lines.find((n) => n.line.key === lineKey);
        if (node) return node.counts.documents;
      }
    }
  }
  return 0;
}

const FAMILY_WORDS: Record<CalculationFamily, string> = { stationary: "stationary fuel", mobile: "mobile fuel", electricity: "electricity", fugitive: "refrigerants" };

/** "3 values move" / "1 value moves". */
function valuesText(n: number): string {
  return n === 1 ? "1 value moves" : `${n} values move`;
}

function processingText(status: string): string {
  const s = status.toLowerCase();
  if (s === "failed" || s === "blocked") return "Could not be read";
  if (s === "queued" || s === "processing" || s === "pending") return "Still reading";
  if (s === "unsupported") return "Not a supported file type";
  return "Needs a document type";
}

/* ============================ long lists ============================ */

/** The documents of one group: all of them when there are 100 or fewer, else a window of the rows near the screen
 *  (an empty spacer stands in for the rest). Row order, keys and the row markup are unchanged. */
function WindowedDocs({ docs, renderRow }: { docs: TreeDocRow[]; renderRow: (doc: TreeDocRow) => ReactNode }) {
  const { host, ...win } = useWindowedRows(docs.length);
  return (
    <div className="s1-et-docs" ref={host as (el: HTMLDivElement | null) => void} onKeyDown={win.onKeyDown}>
      {win.enabled
        ? win.parts.map((p) =>
            p.type === "spacer" ? (
              <div key={`spacer-${p.key}`} aria-hidden style={{ height: p.height }} />
            ) : (
              <div key={docs[p.index].document_id} {...win.rowProps(p.index)}>
                {renderRow(docs[p.index])}
              </div>
            ),
          )
        : docs.map((d) => renderRow(d))}
    </div>
  );
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
  countOnly,
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
  /** Document count only: no bar, no percent (these documents have no values to accept). */
  countOnly?: boolean;
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
            {countOnly ? <span className="s1-et-fill s1-et-fill--count" /> : null}
            {countOnly ? null : <span className="s1-ws-gr__bar s1-et-bar-track" aria-hidden>
              {/* A zero count draws nothing: a segment keeps a minimum width, so it would show as a stub. */}
              {counts.accepted > 0 ? <span className="s1-ws-gr__seg s1-ws-gr__seg--resolved" style={{ flexGrow: counts.accepted }} /> : null}
              {counts.to_review > 0 ? <span className="s1-ws-gr__seg s1-ws-gr__seg--open" style={{ flexGrow: counts.to_review }} /> : null}
              {counts.issues > 0 ? <span className="s1-ws-gr__seg s1-ws-gr__seg--blocking" style={{ flexGrow: counts.issues }} /> : null}
            </span>}
            {countOnly ? null : (
              <span
                className="s1-ws-gr__pct"
                title={`${counts.accepted} of ${counts.values} values accepted${counts.issues ? `, ${counts.issues} with issues` : ""}`}
              >
                {wholePercent(counts.pct_accepted)}% accepted
              </span>
            )}
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
function Dialog({ title, onClose, busy = false, children }: { title: string; onClose: () => void; busy?: boolean; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  const working = useRef(busy);
  useEffect(() => {
    close.current = onClose;
    working.current = busy;
  });
  useEffect(() => {
    box.current?.querySelector<HTMLElement>("input, select, textarea, button:not([disabled])")?.focus();
    const onKey = (e: KeyboardEvent) => {
      // While a request is running the window stays: closing it would hide the answer (and let the user switch
      // engagement before it lands).
      if (e.key === "Escape" && !working.current) close.current();
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
  onMove: (to: string, reread?: RereadChoice) => Promise<void>;
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
  const toLine = lineMap.get(to);
  const fromSummary = from === BLOCK_SUMMARY || section === BLOCK_SUMMARY;
  // What changes: the values this placement holds, and the lines whose calculations read them.
  let consequence: string | null = null;
  const rereadAs = toLine?.read_as && doc.detected_type !== toLine.read_as ? toLine.read_as : null;
  if (needsConfirm && !fromSummary && !rereadAs) {
    const n = doc.values;
    const fromName = lineMap.has(from) ? placeLabel(from) : null;
    const toName = toLine ? placeLabel(to) : null;
    if (n === 0) consequence = "This document has no values yet, so no calculation changes.";
    else if (fromName && toName) consequence = `${valuesText(n)} from ${fromName} to ${toName}. Both lines' calculations change.`;
    else if (toName) consequence = `${valuesText(n)} to ${toName}. Its calculation changes.`;
    else if (fromName) consequence = `${valuesText(n)} out of ${fromName}. Its calculation changes.`;
  }
  // A re-read takes the document off every other line it is on, so the reviewer chooses.
  const alsoOn = rereadAs ? doc.also_in.filter((k) => k !== to && k !== from && lineMap.has(k)).map(placeLabel) : [];
  const choosing = confirming && alsoOn.length > 0;
  // Moves that are allowed but whose values will not count where they land. A line that holds a document type
  // reads the document again as that type, so its values are new, and start unreviewed.
  let warning: string | null = null;
  if (rereadAs) {
    warning = `The document will be read again as ${rereadAs}. The values it gives start unreviewed, and the earlier reading stays in the record.`;
  } else if (toLine && fromSummary) {
    warning = "Summary documents are reference only. Moving it onto this line makes any values it holds count in this line's calculation.";
  } else if (to === BLOCK_SUMMARY && !fromSummary) {
    warning = "Summary documents are reference only. Moving it there stops its values counting in any calculation.";
  } else if (toLine && doc.value_family && toLine.family !== doc.value_family) {
    const why = toLine.family ? `it calculates ${FAMILY_WORDS[toLine.family]}` : "no calculation reads this kind of line";
    warning = `These values won't count on this line, because ${why}. They will show as not placed.`;
  }

  return (
    <Dialog title="Move to…" onClose={onCancel} busy={busy}>
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
      {warning ? (
        <p className="s1-modal__note" role="status">
          {warning}
        </p>
      ) : null}
      {choosing ? (
        <p className="s1-modal__note" role="alert">
          {doc.file_name} is also on {alsoOn.join(" and ")}. Re-reading it as {rereadAs} takes it off those lines.
        </p>
      ) : confirming ? (
        <p className="s1-modal__note" role="alert">
          {consequence ?? `This changes the calculation for ${affected.join(" and ")}.`}
        </p>
      ) : null}
      {error ? (
        <p className="s1-modal__note" role="alert">
          Not moved. {error}
        </p>
      ) : null}
      <div className="s1-modal__actions">
        {choosing ? (
          <>
            {/* The safe choice has the focus: it moves only this placement and leaves the document as it is. */}
            <button className="s1-button s1-button--pri" type="button" autoFocus disabled={busy} onClick={() => void run(() => onMove(to, "move_only"))}>
              Move without re-reading
            </button>
            <button className="s1-button" type="button" disabled={busy} onClick={() => void run(() => onMove(to, "reread"))}>
              Re-read and move
            </button>
          </>
        ) : (
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
        )}
        <button className="s1-linklike" type="button" onClick={confirming ? () => setConfirming(false) : onCancel}>
          {confirming ? "Back" : "Cancel"}
        </button>
      </div>
    </Dialog>
  );
}

function FolderMoveDialog({
  doc,
  folders,
  onError,
  onCancel,
  onMove,
}: {
  doc: TreeDocRow;
  folders: TreeFolder[];
  onError: OnError;
  onCancel: () => void;
  onMove: (folderId: string | null) => Promise<void>;
}) {
  const current = doc.folder_id ?? "";
  const [to, setTo] = useState(current);
  const { busy, error, run } = useSubmit(onError);
  return (
    <Dialog title="Move to folder…" onClose={onCancel} busy={busy}>
      <label className="s1-modal__field">
        <span>Move {doc.file_name} to</span>
        <select value={to} disabled={busy} onChange={(e) => setTo(e.target.value)} aria-label="Folder">
          <option value="">Top of Summary documents and workbook</option>
          {[...folders]
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((f) => (
              <option key={f.folder_id} value={f.folder_id}>
                {f.name}
              </option>
            ))}
        </select>
      </label>
      {error ? (
        <p className="s1-modal__note" role="alert">
          Not moved. {error}
        </p>
      ) : null}
      <div className="s1-modal__actions">
        <button className="s1-button s1-button--pri" type="button" disabled={busy || to === current} onClick={() => void run(() => onMove(to || null))}>
          Move
        </button>
        <button className="s1-linklike" type="button" disabled={busy} onClick={onCancel}>
          Cancel
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
      <Dialog title={title} onClose={onCancel} busy={busy}>
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
    <Dialog title={title} onClose={onCancel} busy={busy}>
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
        <button className="s1-linklike" type="button" disabled={busy} onClick={onCancel}>
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
  maxLength = 120,
  check,
  onError,
  onCancel,
  onSubmit,
}: {
  title: string;
  label: string;
  initial: string;
  action: string;
  /** The longest name the field takes (120 unless the thing named has a shorter limit). */
  maxLength?: number;
  /** A sentence for a name that can't be used (shown at once, the action waits); null when it is fine. */
  check?: (name: string) => string | null;
  onError: OnError;
  onCancel: () => void;
  onSubmit: (value: string) => Promise<void>;
}) {
  const [value, setValue] = useState(initial);
  const { busy, error, run } = useSubmit(onError);
  const text = value.trim();
  const problem = text && text !== initial ? (check?.(text) ?? null) : null;
  return (
    <Dialog title={title} onClose={onCancel} busy={busy}>
      <label className="s1-modal__field">
        <span>{label}</span>
        <input
          className="s1-inline-input"
          value={value}
          maxLength={maxLength}
          aria-invalid={problem ? true : undefined}
          onChange={(e) => setValue(e.target.value)}
        />
      </label>
      {problem ? (
        <p className="s1-modal__note" role="alert">
          {problem}
        </p>
      ) : null}
      {error ? (
        <p className="s1-modal__note" role="alert">
          Not saved. {error}
        </p>
      ) : null}
      <div className="s1-modal__actions">
        <button className="s1-button s1-button--pri" type="button" disabled={!text || text === initial || Boolean(problem) || busy} onClick={() => void run(() => onSubmit(text))}>
          {action}
        </button>
        <button className="s1-linklike" type="button" disabled={busy} onClick={onCancel}>
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
    <Dialog title={title} onClose={onCancel} busy={busy}>
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
        <button className="s1-linklike" type="button" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </Dialog>
  );
}

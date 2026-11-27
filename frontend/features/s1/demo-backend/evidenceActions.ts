/**
 * The demo's copy of the server's Evidence actions (`backend/app/api/evidence_actions.py`): add,
 * rename and delete a line, move a document, and the log of those changes. Same sentences, same
 * rules: a stale `from` is a 409, deleting a line moves its documents to Unassigned supporting
 * evidence with explicit moves, a document's moves are compacted, and every change is logged with
 * the signed-in person. State lives in memory for the tab. Block 1 folders (create, rename, delete, put a
 * document in or out) follow the server's rules too.
 */
import type { EngagementConfig } from "../types/engagement";
import type { EvidenceActivityItem, EvidenceFolderSetting, EvidenceLineSetting, FolderAnswer, LineAnswer, Placement } from "../api/evidenceTree";
import type { DocumentDecision } from "../types/evidence";
import { demoError } from "./index";
import { BLOCK_SUMMARY, CATEGORY_SCOPE, SUPPORTING_UNASSIGNED, applyMoves, buildModel, engagementNow, lineKey, newLineProblem, stampDemoLines, type Model } from "./linesModel";
import { demoDecisions, saveDemoDecision, setDemoEngagement } from "./state";
import type { DemoRoute } from "./types";

const events = new Map<string, EvidenceActivityItem[]>(); // per engagement, oldest first
const MAX_MOVES = 200;
const BLOCKS: Record<string, string> = {
  "block:summary": "Summary documents and workbook",
  "block:unassigned": "Unassigned documents",
  "supporting:unassigned": "Unassigned supporting evidence",
};
const STALE = "This document was already moved from there. Reload Evidence to see where it is now.";

export function demoEvidenceEvents(engagementId: string): EvidenceActivityItem[] {
  return [...(events.get(engagementId) ?? [])].reverse();
}

function actor(): string {
  const engagement = engagementNow();
  return engagement.engagementTeam?.find((m) => m.login === engagement.signedInLogin)?.name ?? engagement.signedInName ?? "You";
}

function log(item: Omit<EvidenceActivityItem, "id" | "at" | "actor_name">): void {
  const id = engagementNow().engagementId;
  const list = events.get(id) ?? [];
  list.push({ id: `demo-${list.length + 1}`, at: new Date().toISOString(), actor_name: actor(), ...item });
  events.set(id, list);
}

function placeLabel(model: Model, key: string): string {
  const line = model.lines.find((l) => l.key === key);
  return BLOCKS[key] ?? (line ? `${line.level2_label} · ${line.label}` : key);
}

function storedLines(): EvidenceLineSetting[] {
  return [...(engagementNow().evidenceLines ?? [])];
}

function saveLines(lines: EvidenceLineSetting[]): void {
  setDemoEngagement({ ...engagementNow(), evidenceLines: lines });
}

function keyFor(e: EvidenceLineSetting): string {
  return lineKey(CATEGORY_SCOPE[e.category] ?? e.scope ?? "", e.category, e.level2 ?? e.level2_label, e.anchor_kind, e.anchor_id);
}

const keyOf = (e: EvidenceLineSetting): string => e.key ?? keyFor(e);

/**
 * The server's `derive_placements` for the demo, where a document has one default place: the saved chain is
 * derived from where the document is filed now, so it has at most one move however often it was moved. The full
 * chain is kept only when the derived one would file the document somewhere else.
 */
export function deriveMoves(defaultTarget: string, chain: Placement[], move: Placement, known: Set<string>): Placement[] {
  const full = [...chain, move];
  const place = (moves: Placement[]) => applyMoves([{ target: defaultTarget, flags: [] }], moves, known)[0]?.target ?? defaultTarget;
  const now = place(full);
  const derived = now === defaultTarget ? [] : [{ from: defaultTarget, to: now }];
  return place(derived) === now ? derived : full;
}

function chainWith(documentId: string, move: Placement, defaultTarget: string, known: Set<string>): Placement[] {
  return chainFrom((demoDecisions().get(documentId)?.placements ?? []) as Placement[], move, defaultTarget, known);
}

function chainFrom(before: Placement[], move: Placement, defaultTarget: string, known: Set<string>): Placement[] {
  const full = deriveMoves(defaultTarget, before, move, known);
  if (full.length > MAX_MOVES) demoError(409, "This document has been moved too many times to save another move. Ask Sustentra support to tidy its history.");
  return full;
}

function saveChain(documentId: string, chain: Placement[]): DocumentDecision {
  const decision = { ...(demoDecisions().get(documentId) ?? {}), documentId, placements: chain } as DocumentDecision;
  saveDemoDecision(decision);
  return decision;
}

export const MAX_FOLDERS = 50;
const MAX_FOLDER_NAME = 120;
let folderCounter = 0;

/** The server's `clean_folder_name`: Unicode NFC, inner whitespace collapsed, trimmed; a sentence when it can't be used. */
export function cleanFolderName(raw: unknown): string {
  const name = typeof raw === "string" ? raw.normalize("NFC").split(/\s+/u).filter(Boolean).join(" ") : "";
  if (!name) return demoError(422, "Give the folder a name.");
  if (/\p{C}/u.test(name)) return demoError(422, "A folder name can't contain control characters.");
  if ([...name].length > MAX_FOLDER_NAME) return demoError(422, `A folder name can be at most ${MAX_FOLDER_NAME} characters.`);
  return name;
}

const nameKey = (name: string) => name.normalize("NFC").toLowerCase();
const storedFolders = (): EvidenceFolderSetting[] => [...(engagementNow().evidenceFolders ?? [])];
const saveFolders = (folders: EvidenceFolderSetting[]) => setDemoEngagement({ ...engagementNow(), evidenceFolders: folders });
const folderAnswer = (folders: EvidenceFolderSetting[], extra: Partial<FolderAnswer> = {}): FolderAnswer => ({ ...extra, evidenceFolders: folders });

function freshName(raw: unknown, folders: EvidenceFolderSetting[], exceptId?: string): string {
  const name = cleanFolderName(raw);
  if (folders.some((f) => f.id !== exceptId && nameKey(f.name) === nameKey(name))) demoError(409, "A folder with that name already exists. Use another name.");
  return name;
}

function folderOr404(folders: EvidenceFolderSetting[], id: string): EvidenceFolderSetting {
  return folders.find((f) => f.id === id) ?? demoError(404, "This folder was already deleted. Reload Evidence to see the current folders.");
}

const answer = (lines: EvidenceLineSetting[], extra: Partial<LineAnswer> = {}): LineAnswer => ({ ...extra, evidenceLines: lines });

export const MAX_LEVEL2_NAME = 80;

/** The server's `clean_level2_name`: Unicode NFC, inner whitespace collapsed, trimmed; a sentence when it can't be used. */
export function cleanLevel2Name(raw: unknown): string {
  const name = typeof raw === "string" ? raw.normalize("NFC").split(/\s+/u).filter(Boolean).join(" ") : "";
  if (!name) return demoError(422, "Give the fuel a name.");
  if (/\p{C}/u.test(name)) return demoError(422, "A fuel name can't contain control characters.");
  if ([...name].length > MAX_LEVEL2_NAME) return demoError(422, `A fuel name can be at most ${MAX_LEVEL2_NAME} characters.`);
  return name;
}

const level2Names = () => ({ ...(engagementNow().evidenceLevel2Names ?? {}) });
const saveLevel2Names = (names: NonNullable<EngagementConfig["evidenceLevel2Names"]>) =>
  setDemoEngagement({ ...engagementNow(), evidenceLevel2Names: names });

/** Every document filed on one of the lines in `gone` moves to Unassigned supporting evidence, by explicit moves (the server's `_move_to_unassigned`). */
function moveOffLines(gone: Set<string>): { changed: Record<string, DocumentDecision>; moved: number } {
  const model = buildModel();
  const knownAfter = new Set(model.lines.map((l) => l.key).filter((k) => !gone.has(k)));
  const changed: Record<string, DocumentDecision> = {};
  let moved = 0;
  for (const r of model.records) {
    let chain = (demoDecisions().get(r.documentId)?.placements ?? []) as Placement[];
    let touched = false;
    for (const key of [...gone].sort()) {
      if (!applyMoves([{ target: r.defaultTarget, flags: [] }], chain, new Set(model.lines.map((l) => l.key))).some((s) => s.target === key)) continue;
      chain = chainFrom(chain, { from: key, to: SUPPORTING_UNASSIGNED }, r.defaultTarget, knownAfter);
      touched = true;
    }
    if (!touched) continue;
    changed[r.documentId] = saveChain(r.documentId, chain);
    moved += 1;
  }
  // A set-aside document that was moved to a line keeps a move out, as on the server.
  const shown = new Set(model.records.map((r) => r.documentId));
  for (const [documentId, decision] of demoDecisions()) {
    let chain = (decision.placements ?? []) as Placement[];
    if (shown.has(documentId) || chain.length >= MAX_MOVES) continue;
    const onGone = [...gone].filter((key) => chain.some((m) => m.to === key));
    for (const key of onGone.sort()) chain = [...chain, { from: key, to: SUPPORTING_UNASSIGNED }];
    if (onGone.length) changed[documentId] = saveChain(documentId, chain);
  }
  return { changed, moved };
}

export const evidenceActionRoutes: DemoRoute[] = [
  {
    method: "POST",
    path: /^\/engagements\/(?<id>[^/]+)\/evidence-lines$/,
    handle: ({ body }) => {
      let entry = (body ?? {}) as EvidenceLineSetting;
      if (!entry.level2 && entry.level2_label) {
        // A name a reviewer gave a fuel is that fuel, whatever it was called before (the server's lookup).
        const wanted = nameKey(entry.level2_label.trim());
        for (const [id, renamed] of Object.entries(level2Names())) {
          const [category, level2] = [id.slice(0, id.indexOf(":")), id.slice(id.indexOf(":") + 1)];
          if (category === entry.category && nameKey(renamed.label) === wanted) entry = { ...entry, level2 };
        }
      }
      const stored = storedLines();
      if (!entry.category || !entry.level2_label?.trim() || !entry.label?.trim() || !entry.anchor_kind) demoError(422, "each line needs a category, a name, an anchor and a label");
      if (entry.label.length > 120 || entry.level2_label.length > 120) demoError(422, "labels must be at most 120 characters");
      const problem = newLineProblem(engagementNow(), [...stored, entry]);
      if (problem) demoError(422, problem);
      const model = buildModel();
      const key = keyFor(entry);
      if (stored.some((l) => keyOf(l) === key)) demoError(409, "That line already exists. Use the existing line.");
      if (model.lines.some((l) => l.key === key && !l.created_by_user)) {
        demoError(422, `${key} is a line the system already creates for this engagement, so it can't be added as your own. Use the existing line.`);
      }
      const [line] = stampDemoLines({ ...engagementNow(), evidenceLines: [] }, [{ ...entry, key }], engagementNow().signedInLogin ?? "demo", new Date().toISOString());
      const lines = [...stored, line];
      saveLines(lines);
      log({ event_type: "evidence_line_created", line_key: key, label: entry.label.trim(), level2_label: entry.level2_label.trim() });
      return answer(lines, { line });
    },
  },
  {
    method: "PATCH",
    path: /^\/engagements\/(?<id>[^/]+)\/evidence-lines\/(?<key>[^/]+)$/,
    handle: ({ params, body }) => {
      const stored = storedLines();
      const found = stored.find((l) => keyOf(l) === params.key);
      if (!found) demoError(404, "That line isn't one added to this engagement. Lines the system creates can't be renamed or deleted.");
      const label = String((body as { label?: string } | null)?.label ?? "").trim();
      if (!label) demoError(422, "Give the line a name.");
      if (label.length > 120) demoError(422, "labels must be at most 120 characters");
      if (label === found.label) return answer(stored, { line: found });
      const renamed = { ...found, label };
      const lines = stored.map((l) => (l === found ? renamed : l));
      saveLines(lines);
      log({ event_type: "evidence_line_renamed", line_key: params.key, old_label: found.label, new_label: label });
      return answer(lines, { line: renamed });
    },
  },
  {
    method: "DELETE",
    path: /^\/engagements\/(?<id>[^/]+)\/evidence-lines\/(?<key>[^/]+)$/,
    handle: ({ params }) => {
      const stored = storedLines();
      const found = stored.find((l) => keyOf(l) === params.key);
      if (!found) demoError(404, "That line isn't one added to this engagement. Lines the system creates can't be renamed or deleted.");
      const model = buildModel();
      const knownAfter = new Set(model.lines.map((l) => l.key));
      knownAfter.delete(params.key);
      const on = model.records.filter((r) => model.slots.get(r.documentId)?.some((s) => s.target === params.key));
      const changed: Record<string, DocumentDecision> = {};
      for (const r of on) changed[r.documentId] = saveChain(r.documentId, chainWith(r.documentId, { from: params.key, to: SUPPORTING_UNASSIGNED }, r.defaultTarget, knownAfter));
      // A set-aside document that was moved to the line keeps a move out, as on the server.
      const shown = new Set(model.records.map((r) => r.documentId));
      for (const [documentId, decision] of demoDecisions()) {
        const chain = (decision.placements ?? []) as Placement[];
        if (!shown.has(documentId) && chain.some((m) => m.to === params.key) && chain.length < MAX_MOVES) {
          changed[documentId] = saveChain(documentId, [...chain, { from: params.key, to: SUPPORTING_UNASSIGNED }]);
        }
      }
      const lines = stored.filter((l) => l !== found);
      saveLines(lines);
      log({ event_type: "evidence_line_deleted", line_key: params.key, label: found.label, documents_moved: on.length });
      return answer(lines, { documents_moved: on.length, documents: changed });
    },
  },
  {
    // Rename a fuel (Level 2): only the name shown changes; the id stays (the server's `rename_fuel`).
    method: "PATCH",
    path: /^\/engagements\/(?<id>[^/]+)\/evidence-fuels\/(?<category>[^/]+)\/(?<level2>[^/]+)$/,
    handle: ({ params, body }) => {
      const group = buildModel().lines.filter((l) => l.category === params.category && l.level2 === params.level2);
      if (!CATEGORY_SCOPE[params.category] || !group.length) demoError(404, "This fuel was already deleted. Reload Evidence to see the current fuels.");
      const name = cleanLevel2Name((body as { name?: unknown } | null)?.name);
      const old = group[0].level2_label;
      const names = level2Names();
      if (name === old) return { level2: { category: params.category, level2: params.level2, label: old }, evidenceLevel2Names: names };
      const taken = buildModel().lines.some((l) => l.category === params.category && l.level2 !== params.level2 && nameKey(l.level2_label) === nameKey(name));
      if (taken) demoError(409, `${name} already exists in this category. Use another name.`, "level2_name_taken");
      const next = { ...names, [`${params.category}:${params.level2}`]: { label: name, renamed_by: engagementNow().signedInLogin ?? "demo", renamed_at: new Date().toISOString() } };
      saveLevel2Names(next);
      log({ event_type: "evidence_level2_renamed", old_label: old, new_label: name });
      return { level2: { category: params.category, level2: params.level2, label: name }, evidenceLevel2Names: next };
    },
  },
  {
    // Delete a fuel the reviewers made, with its lines; its documents go to Unassigned supporting evidence (the server's `delete_fuel`).
    method: "DELETE",
    path: /^\/engagements\/(?<id>[^/]+)\/evidence-fuels\/(?<category>[^/]+)\/(?<level2>[^/]+)$/,
    handle: ({ params }) => {
      const group = buildModel().lines.filter((l) => l.category === params.category && l.level2 === params.level2);
      if (!CATEGORY_SCOPE[params.category] || !group.length) demoError(404, "This fuel was already deleted. Reload Evidence to see the current fuels.");
      if (group.some((l) => !l.created_by_user)) demoError(409, "Created by the system from your Setup; can't be deleted.", "level2_system_created");
      const gone = new Set(group.map((l) => l.key));
      const { changed, moved } = moveOffLines(gone);
      const lines = storedLines().filter((l) => !gone.has(keyOf(l)));
      saveLines(lines);
      const names = level2Names();
      delete names[`${params.category}:${params.level2}`];
      saveLevel2Names(names);
      log({ event_type: "evidence_level2_deleted", label: group[0].level2_label, lines_deleted: gone.size, documents_moved: moved });
      return { ...answer(lines, { documents_moved: moved, documents: changed }), evidenceLevel2Names: names };
    },
  },
  {
    method: "POST",
    path: /^\/engagements\/(?<id>[^/]+)\/documents\/(?<doc>[^/]+)\/placements$/,
    handle: ({ params, body }) => {
      const { from, to } = (body ?? {}) as Placement;
      const model = buildModel();
      const record = model.records.find((r) => r.documentId === params.doc);
      if (!record) demoError(404, "That document isn't on the Evidence page for this engagement.");
      if (!(model.slots.get(params.doc) ?? []).some((s) => s.target === from)) demoError(409, STALE);
      const known = new Set(model.lines.map((l) => l.key));
      if (!known.has(to) && !(to in BLOCKS)) demoError(422, "That line no longer exists. Reload Evidence and pick another place.");
      if (from === to) demoError(422, "The document is already there.");
      if (from === BLOCK_SUMMARY && demoDecisions().get(params.doc)?.folderId) {
        const { folderId: _out, ...rest } = demoDecisions().get(params.doc)!; // it leaves Block 1, so it leaves its folder
        void _out;
        saveDemoDecision(rest as DocumentDecision);
      }
      const payload = saveChain(params.doc, chainWith(params.doc, { from, to }, record.defaultTarget, known));
      log({ event_type: "evidence_document_moved", document_id: params.doc, from_label: placeLabel(model, from), to_label: placeLabel(model, to) });
      return { document_id: params.doc, payload };
    },
  },
  {
    // The reviewer places a document on a Setup facility: their own decision, logged (the server's `set_document_facility`).
    method: "POST",
    path: /^\/engagements\/(?<id>[^/]+)\/documents\/(?<doc>[^/]+)\/facility$/,
    handle: ({ params, body }) => {
      const facilityId = String((body as { facility_id?: unknown } | undefined)?.facility_id ?? "");
      const model = buildModel();
      if (!model.records.some((r) => r.documentId === params.doc)) demoError(404, "That document isn't on the Evidence page for this engagement.");
      const facility = model.facilities.find((f) => f.facilityId === facilityId);
      if (!facility) demoError(422, "That facility is not in Setup. Reload Evidence and pick another.");
      const existing = demoDecisions().get(params.doc);
      if (existing?.facilityId === facilityId) return { document_id: params.doc, payload: existing }; // already there: nothing written or logged
      const expected = (body as { expected_facility_id?: string | null } | undefined)?.expected_facility_id;
      if (expected !== undefined && (existing?.facilityId ?? null) !== (expected ?? null)) {
        demoError(409, "Another reviewer already chose a facility for this document. Reload Evidence to see it.");
      }
      if (existing?.placements?.length) {
        demoError(409, "This document was moved by hand. Move it back to Unassigned first, or place it from the Evidence tree.");
      }
      // The demo has no Claude suggestions, so a placement here is never one (the server's rule is the tree row's).
      const record = model.records.find((r) => r.documentId === params.doc) as { facilitySuggestion?: { facilityId: string } } | undefined;
      const suggested = record?.facilitySuggestion?.facilityId === facilityId;
      const decision = { ...(existing ?? {}), documentId: params.doc, facilityId } as DocumentDecision;
      saveDemoDecision(decision);
      log({ event_type: "evidence_document_facility_set", document_id: params.doc, facility_id: facilityId, facility_name: facility!.name, suggested });
      return { document_id: params.doc, payload: decision };
    },
  },
  {
    method: "POST",
    path: /^\/engagements\/(?<id>[^/]+)\/evidence-folders$/,
    handle: ({ body }) => {
      const folders = storedFolders();
      if (folders.length >= MAX_FOLDERS) demoError(422, `An engagement can have at most ${MAX_FOLDERS} folders.`);
      const name = freshName((body as { name?: unknown } | null)?.name, folders);
      folderCounter += 1;
      const folder: EvidenceFolderSetting = { id: `fld-demo${folderCounter}`, name, created_by: engagementNow().signedInLogin ?? "demo", created_at: new Date().toISOString() };
      const next = [...folders, folder];
      saveFolders(next);
      log({ event_type: "evidence_folder_created", folder_id: folder.id, folder_name: name });
      return folderAnswer(next, { folder });
    },
  },
  {
    method: "PATCH",
    path: /^\/engagements\/(?<id>[^/]+)\/evidence-folders\/(?<folder>[^/]+)$/,
    handle: ({ params, body }) => {
      const folders = storedFolders();
      const found = folderOr404(folders, params.folder);
      const name = freshName((body as { name?: unknown } | null)?.name, folders, found.id);
      if (name === found.name) return folderAnswer(folders, { folder: found });
      const renamed = { ...found, name };
      const next = folders.map((f) => (f === found ? renamed : f));
      saveFolders(next);
      log({ event_type: "evidence_folder_renamed", folder_id: found.id, old_label: found.name, new_label: name });
      return folderAnswer(next, { folder: renamed });
    },
  },
  {
    method: "DELETE",
    path: /^\/engagements\/(?<id>[^/]+)\/evidence-folders\/(?<folder>[^/]+)$/,
    handle: ({ params }) => {
      const folders = storedFolders();
      const found = folderOr404(folders, params.folder);
      const shown = new Set(buildModel().records.map((r) => r.documentId));
      const changed: Record<string, DocumentDecision> = {};
      let moved = 0;
      for (const [documentId, decision] of [...demoDecisions()]) {
        if (decision.folderId !== found.id) continue;
        const { folderId: _gone, ...rest } = decision; // the document goes to the top of Block 1
        void _gone;
        saveDemoDecision(rest as DocumentDecision);
        changed[documentId] = rest as DocumentDecision;
        if (shown.has(documentId)) moved += 1;
      }
      const next = folders.filter((f) => f !== found);
      saveFolders(next);
      log({ event_type: "evidence_folder_deleted", folder_id: found.id, folder_name: found.name, documents_moved: moved });
      return folderAnswer(next, { documents_moved: moved, documents: changed });
    },
  },
  {
    method: "POST",
    path: /^\/engagements\/(?<id>[^/]+)\/documents\/(?<doc>[^/]+)\/folder$/,
    handle: ({ params, body }) => {
      const requested = (body as { folder_id?: string | null } | null)?.folder_id ?? null;
      const model = buildModel();
      if (!model.records.some((r) => r.documentId === params.doc)) demoError(404, "That document isn't on the Evidence page for this engagement.");
      if (!(model.slots.get(params.doc) ?? []).some((s) => s.target === BLOCK_SUMMARY)) {
        demoError(422, "Only documents in Summary documents and workbook can go in a folder.");
      }
      const folders = storedFolders();
      const target = requested === null ? null : folderOr404(folders, requested);
      const existing = demoDecisions().get(params.doc);
      const current = folders.find((f) => f.id === existing?.folderId) ?? null;
      if ((current?.id ?? null) === (target?.id ?? null)) return { document_id: params.doc, payload: existing ?? ({ documentId: params.doc } as DocumentDecision) };
      const { folderId: _old, ...rest } = existing ?? ({ documentId: params.doc } as DocumentDecision);
      void _old;
      const payload = { ...rest, documentId: params.doc, ...(target ? { folderId: target.id } : {}) } as DocumentDecision;
      saveDemoDecision(payload);
      log({ event_type: "evidence_document_folder_set", document_id: params.doc, folder_id: target?.id ?? null, from_label: current?.name ?? BLOCKS[BLOCK_SUMMARY], to_label: target?.name ?? BLOCKS[BLOCK_SUMMARY] });
      return { document_id: params.doc, payload };
    },
  },
  {
    method: "GET",
    path: /^\/engagements\/(?<id>[^/]+)\/evidence-activity$/,
    handle: ({ params }) => ({ items: demoEvidenceEvents(params.id), next_cursor: null }),
  },
];

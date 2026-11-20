/**
 * The demo's copy of the server's Evidence actions (`backend/app/api/evidence_actions.py`): add,
 * rename and delete a line, move a document, and the log of those changes. Same sentences, same
 * rules: a stale `from` is a 409, deleting a line moves its documents to Unassigned supporting
 * evidence with explicit moves, a document's moves are compacted, and every change is logged with
 * the signed-in person. State lives in memory for the tab.
 */
import type { EvidenceActivityItem, EvidenceLineSetting, LineAnswer, Placement } from "../api/evidenceTree";
import type { DocumentDecision } from "../types/evidence";
import { demoError } from "./index";
import { CATEGORY_SCOPE, SUPPORTING_UNASSIGNED, applyMoves, buildModel, engagementNow, lineKey, newLineProblem, stampDemoLines, type Model } from "./linesModel";
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
  const before = (demoDecisions().get(documentId)?.placements ?? []) as Placement[];
  const full = deriveMoves(defaultTarget, before, move, known);
  if (full.length > MAX_MOVES) demoError(409, "This document has been moved too many times to save another move. Ask Sustentra support to tidy its history.");
  return full;
}

function saveChain(documentId: string, chain: Placement[]): DocumentDecision {
  const decision = { ...(demoDecisions().get(documentId) ?? {}), documentId, placements: chain } as DocumentDecision;
  saveDemoDecision(decision);
  return decision;
}

const answer = (lines: EvidenceLineSetting[], extra: Partial<LineAnswer> = {}): LineAnswer => ({ ...extra, evidenceLines: lines });

export const evidenceActionRoutes: DemoRoute[] = [
  {
    method: "POST",
    path: /^\/engagements\/(?<id>[^/]+)\/evidence-lines$/,
    handle: ({ body }) => {
      const entry = (body ?? {}) as EvidenceLineSetting;
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
      const decision = { ...(demoDecisions().get(params.doc) ?? {}), documentId: params.doc, facilityId } as DocumentDecision;
      saveDemoDecision(decision);
      log({ event_type: "evidence_document_facility_set", document_id: params.doc, facility_id: facilityId, facility_name: facility!.name, suggested: false });
      return { document_id: params.doc, payload: decision };
    },
  },
  {
    method: "GET",
    path: /^\/engagements\/(?<id>[^/]+)\/evidence-activity$/,
    handle: ({ params }) => ({ items: demoEvidenceEvents(params.id), next_cursor: null }),
  },
];

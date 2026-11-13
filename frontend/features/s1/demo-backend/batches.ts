import type { BatchDocument, BatchDocumentStatus, BatchView } from "../api/documentBatches";
import { ApiError } from "../../../lib/api";
import type { DemoRoute } from "./types";

/**
 * Document batches for the demo: POST makes a batch, GET says how reading it stands
 * (docs/api_contract.md, "Document batches"). The demo has no reader, so each GET is one step of
 * a script over the files the presenter dropped (`registerDemoBatch`, called by the upload
 * path): documents wait, then are read two at a time, a long PDF in page chunks (12 of 30),
 * until the batch is complete and the client stops asking. One document ends `partial` (its last
 * pages unread) and one has a type Claude suggested (never confirmed here).
 */

export interface DemoBatchFile {
  documentId: string;
  fileName: string;
}

interface BatchState {
  batchId: string;
  engagementId: string;
  label: string | null;
  createdAt: string;
  files: DemoBatchFile[];
  polls: number;
}

const batches = new Map<string, BatchState>();
let counter = 0;

/** The pages of the long PDF, and how far each poll of its reading has got. */
const LONG_PDF_PAGES = 30;
const LONG_PDF_STEPS = [6, 12, 20];
const LONG_PDF_UNREAD: [number, number] = [21, 30];
export const PARTIAL_REASON = `Partly read: pages ${LONG_PDF_UNREAD[0]}–${LONG_PDF_UNREAD[1]}.`;

/** The type a file name suggests, in the canonical vocabulary the Evidence screens name. */
function guessTypeId(name: string): string | null {
  const lower = name.toLowerCase();
  if (/electric|power/.test(lower)) return "CT-S2-ELEC";
  if (/steam|thermal|chilled/.test(lower)) return "CT-S2-THERMAL";
  if (/refrig/.test(lower)) return "CT-S1-REFRSVC";
  if (/fleet|fuelcard|mileage|vehicle/.test(lower)) return "CT-S1-MOBFUEL";
  if (/gas|propane|diesel|fuel/.test(lower)) return "CT-S1-FUELQTY";
  return null;
}

function hash(text: string): number {
  let h = 2166136261;
  for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return Math.abs(h);
}

interface Plan {
  start: number;
  span: number;
  longPdf: boolean;
  partial: boolean;
  aiType: boolean;
  typeId: string | null;
}

/** Who is read when, and which document is the long PDF, the partial one and the one Claude typed. */
function planFor(files: DemoBatchFile[]): Plan[] {
  const isPdf = (f: DemoBatchFile) => /\.pdf$/i.test(f.fileName);
  const partialAt = Math.max(0, files.findIndex(isPdf));
  let aiAt = files.findIndex((f, i) => i !== partialAt && guessTypeId(f.fileName) === null);
  if (aiAt < 0) aiAt = files.length > 1 ? (partialAt === 0 ? 1 : 0) : -1;
  return files.map((file, i) => {
    const longPdf = i === partialAt;
    return {
      start: 1 + Math.floor(i / 2),
      span: longPdf ? LONG_PDF_STEPS.length : 1,
      longPdf,
      partial: longPdf,
      aiType: i === aiAt,
      typeId: guessTypeId(file.fileName) ?? (i === aiAt ? "CT-S1-FUELQTY" : null),
    };
  });
}

function itemFor(file: DemoBatchFile, plan: Plan, polls: number): BatchDocument {
  const base = { document_id: file.documentId, file_name: file.fileName };
  if (polls < plan.start) {
    return { ...base, status: "queued", chunks: null, canonical_type_id: null, halt_reason: null, records_found: 0 };
  }
  const step = polls - plan.start;
  if (step < plan.span) {
    const chunks = plan.longPdf
      ? { total: LONG_PDF_PAGES, completed: LONG_PDF_STEPS[step], failed: 0, failed_pages: [] as [number, number][] }
      : null;
    return { ...base, status: "reading", chunks, canonical_type_id: null, halt_reason: null, records_found: 0 };
  }
  const found = 2 + (hash(file.fileName) % 7);
  if (plan.partial) {
    return {
      ...base,
      status: "partial",
      chunks: {
        total: LONG_PDF_PAGES,
        completed: LONG_PDF_UNREAD[0] - 1,
        failed: LONG_PDF_UNREAD[1] - LONG_PDF_UNREAD[0] + 1,
        failed_pages: [LONG_PDF_UNREAD],
      },
      canonical_type_id: plan.typeId ?? "CT-S1-FUELQTY",
      halt_reason: PARTIAL_REASON,
      records_found: Math.max(3, found),
    };
  }
  return { ...base, status: "done", chunks: null, canonical_type_id: plan.typeId, halt_reason: null, records_found: found };
}

/** One step of the batch: the view a GET answers with. */
export function viewOf(state: BatchState): BatchView {
  const plans = planFor(state.files);
  const items = state.files.map((file, i) => itemFor(file, plans[i], state.polls));
  const totals: Record<BatchDocumentStatus, number> = { queued: 0, reading: 0, done: 0, partial: 0, failed: 0, not_started: 0 };
  for (const item of items) totals[item.status] += 1;
  return {
    batch_id: state.batchId,
    engagement_id: state.engagementId,
    label: state.label,
    items,
    totals,
    complete: totals.queued + totals.reading === 0,
  };
}

/** Tells the demo which files a batch holds (the real API learns it from the uploads). */
export function registerDemoBatch(batchId: string, files: DemoBatchFile[]): void {
  const state = batches.get(batchId);
  if (!state) return;
  state.files = files;
  state.polls = 0;
}

/** The document in a batch whose type Claude suggested, once it has been read. */
export function demoBatchAiTypeDocument(files: DemoBatchFile[]): string | null {
  const plans = planFor(files);
  const at = plans.findIndex((p) => p.aiType);
  return at >= 0 ? files[at].documentId : null;
}

export function resetDemoBatches(): void {
  batches.clear();
  counter = 0;
}

export const batchRoutes: DemoRoute[] = [
  {
    method: "POST",
    path: /^\/engagements\/(?<id>[^/]+)\/document-batches$/,
    handle: ({ params, body }) => {
      const label = (body as { label?: unknown } | undefined)?.label;
      counter += 1;
      const state: BatchState = {
        batchId: `BATCH-DEMO-${String(counter).padStart(4, "0")}`,
        engagementId: params.id,
        label: typeof label === "string" && label.trim() ? label.trim() : null,
        createdAt: new Date().toISOString(),
        files: [],
        polls: 0,
      };
      batches.set(state.batchId, state);
      return { batch_id: state.batchId, engagement_id: state.engagementId, label: state.label, created_at: state.createdAt };
    },
  },
  {
    method: "GET",
    path: /^\/engagements\/(?<id>[^/]+)\/document-batches\/(?<batch>[^/]+)$/,
    handle: ({ params }) => {
      const state = batches.get(params.batch);
      if (!state || state.engagementId !== params.id) throw new ApiError(404, "Batch not found.", { detail: "Batch not found." }, null);
      state.polls += 1;
      return viewOf(state);
    },
  },
];

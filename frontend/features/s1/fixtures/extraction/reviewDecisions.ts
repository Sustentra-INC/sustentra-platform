import type { EvidenceItem } from "../../types/evidence";
import type { ReviewValue } from "../../types/review";

/**
 * The review decisions of the demo, laid on the extracted values: which documents the engagement
 * team has accepted, who accepted them and when. Extraction review, the Dashboard counts and the
 * demo backend's schedule (`demo-backend/linesModel.ts`) all read these, so a document is accepted
 * on every screen or on none.
 */

/** Who reviewed the demo's accepted values: the engagement team. */
const TEAM = ["M. Osei", "R. Iqbal", "T. Brandt", "L. Chen"];

function reviewedAt(i: number): string {
  return `2026-01-${String(12 + (i % 6)).padStart(2, "0")}T${String(9 + (i % 8)).padStart(2, "0")}:${String((i * 7) % 60).padStart(2, "0")}:00Z`;
}

/** Bills and statements a reviewer has gone through. Everything else is left open. */
const REVIEWED_TYPES = new Set(["Natural gas bill", "Electricity bill", "Fleet fuel statement", "Other fuel invoice"]);
/** Documents still waiting for a reviewer, so the demo shows work open. */
const NOT_YET_REVIEWED = new Set(["kent_gas_sep_2025.pdf", "modesto_electric_nov_2025.pdf", "modesto_refrigerant_service.pdf"]);
/** The two stress files: reviewed in bulk, the last rows still open. */
const BULK_OPEN = 12;
const BULK = ["mileage_reimbursement_2025.xlsx", "supplier_roster_FY2025.csv"];

const isDone = (v: ReviewValue) => v.reviewState === "accepted" || v.reviewState === "corrected";

function accept(v: ReviewValue, actor: string, at: string): void {
  v.reviewState = "accepted";
  v.record = [...v.record, { kind: "human", actor, at, action: "accepted as read" }];
}

/** Lays the review decisions over the values (in place). */
export function applyReviewDecisions(values: ReviewValue[], evidence: EvidenceItem[]): void {
  const byDoc = new Map<string, ReviewValue[]>();
  for (const v of values) byDoc.set(v.documentId, [...(byDoc.get(v.documentId) ?? []), v]);

  let index = 0;
  for (const doc of evidence) {
    if (doc.evidenceClass !== "main" || doc.disposition === "withdrawn" || doc.processingState === "blocked") continue;
    if (doc.relationships.some((r) => r.kind === "superseded_by") || doc.documentId === "DOC-DUPE-B") continue;
    const type = doc.detectedType;
    if (!type || !(REVIEWED_TYPES.has(type) || type.startsWith("Refrigerant"))) continue;
    if (NOT_YET_REVIEWED.has(doc.filename)) continue;
    const own = (byDoc.get(doc.documentId) ?? []).filter((v) => !v.withdrawn);
    if (!own.length) continue;
    const mine = own.find(isDone)?.record.find((r) => r.kind === "human");
    const actor = mine?.actor ?? TEAM[index % TEAM.length];
    const at = mine?.at ?? reviewedAt(index);
    index += 1;
    for (const v of own) if (v.reviewState === "to_review" && !v.ai && !v.missing) accept(v, actor, at);
  }

  // The stress files: reviewed in bulk by one reviewer, the last rows still open.
  for (const file of BULK) {
    const rows = values.filter((v) => v.filename === file);
    rows.slice(0, Math.max(0, rows.length - BULK_OPEN)).forEach((v, i) => accept(v, "M. Osei", `2025-09-16T${String(9 + (i % 8)).padStart(2, "0")}:${String(i % 60).padStart(2, "0")}:00Z`));
  }
}

export interface DocumentReview {
  /** A reviewer accepted or corrected a value of the document. */
  done: boolean;
  /** Labels of the values a reviewer still has to decide (Claude's suggestions wait on their own). */
  open: string[];
  edited: boolean;
  reviewer: string | null;
  at: string | null;
}

/** What the values say about a document's review: the one reading the demo backend takes. */
export function documentReview(values: ReviewValue[]): DocumentReview {
  const live = values.filter((v) => !v.withdrawn);
  const done = live.filter(isDone);
  const human = done.flatMap((v) => v.record).find((r) => r.kind === "human");
  return {
    done: done.length > 0,
    open: live.filter((v) => !isDone(v) && !v.ai).map((v) => v.whatItIs),
    edited: done.some((v) => v.reviewState === "corrected"),
    reviewer: human?.actor ?? null,
    at: human?.at ?? null,
  };
}

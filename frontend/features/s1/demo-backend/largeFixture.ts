/**
 * Demo backend: a large engagement for checking the Evidence page with hundreds of documents (MVP-160).
 *
 * Off unless the build or dev server is started with NEXT_PUBLIC_S1_DEMO_DOCS=<n> (for example 500); the normal
 * demo never sees it. It pads the tree with synthetic documents, spread over the lines the demo already has (so
 * every facility and category shows), plus 30 in Block 1 and 10 unassigned, and keeps every count and line total
 * consistent. Nothing is written anywhere.
 */
import type { EvidenceTree, TreeCounts, TreeDocRow } from "../api/evidenceTree";

export const SUMMARY_PADDING = 30;
export const UNASSIGNED_PADDING = 10;

/** How many documents the engagement should have, or null in the normal demo. */
export function largeFixtureSize(): number | null {
  // Never in a production build, even if the variable is set (a production start is the real demo)
  if (process.env.NODE_ENV === "production" && process.env.NEXT_PUBLIC_S1_DEMO_DOCS_ALLOW_PRODUCTION !== "1") return null;
  const raw = process.env.NEXT_PUBLIC_S1_DEMO_DOCS;
  const n = raw ? Number.parseInt(raw, 10) : NaN;
  return Number.isFinite(n) && n > 0 && n <= 5000 ? n : null;
}

const addCounts = (c: TreeCounts, documents: number, values: number, accepted: number): void => {
  c.documents += documents;
  c.values += values;
  c.accepted += accepted;
  c.to_review = Math.max(0, c.values - c.accepted - c.issues);
  c.pct_accepted = c.values ? Math.round((1000 * c.accepted) / c.values) / 10 : 0;
};

function synthetic(index: number, over: Partial<TreeDocRow>): TreeDocRow {
  const month = String((index % 12) + 1).padStart(2, "0");
  const last = new Date(Date.UTC(2025, (index % 12) + 1, 0)).getUTCDate();
  return {
    document_id: `DEMO-LARGE-${String(index).padStart(4, "0")}`,
    file_name: `Demo bill ${String(index).padStart(4, "0")}.pdf`,
    period_start: `2025-${month}-01`,
    period_end: `2025-${month}-${last}`,
    facility_id: null,
    facility_name: null,
    processing_status: "completed",
    detected_type: "Utility bill",
    also_in: [],
    value_family: null,
    values: 20,
    accepted: 14,
    flags: [],
    ...over,
  };
}

/** The tree with documents added until the engagement has ``total`` (never fewer than it already has). */
export function padTree(tree: EvidenceTree, total: number): EvidenceTree {
  const lines = tree.blocks.supporting.scopes.flatMap((scope) =>
    scope.categories.flatMap((category) => category.level2s.flatMap((level2) => level2.lines.map((node) => ({ node, scope, category, level2 })))),
  );
  const have = new Set<string>();
  const note = (rows: TreeDocRow[]) => rows.forEach((r) => have.add(r.document_id));
  note(tree.blocks.summary);
  note(tree.blocks.unassigned);
  note(tree.blocks.supporting.unassigned);
  lines.forEach((l) => note(l.node.documents));
  let index = 0;
  const bump = (counts: (TreeCounts | undefined)[], row: TreeDocRow, valued: boolean) =>
    counts.forEach((c) => c && addCounts(c, 1, valued ? row.values : 0, valued ? row.accepted : 0));
  for (let i = 0; i < SUMMARY_PADDING && have.size < total; i++) {
    const row = synthetic(index++, { values: 0, accepted: 0, folder_id: null, detected_type: "Inventory workbook", placement_from: "block:summary" });
    tree.blocks.summary.push(row);
    have.add(row.document_id);
    bump([tree.blocks.summary_counts], row, false);
  }
  for (let i = 0; i < UNASSIGNED_PADDING && have.size < total; i++) {
    const row = synthetic(index++, { detected_type: "Unknown", processing_status: "needs_type", values: 0, accepted: 0, placement_from: "block:unassigned" });
    tree.blocks.unassigned.push(row);
    have.add(row.document_id);
    bump([tree.blocks.unassigned_counts], row, false);
  }
  // a few busy lines (one per category where there is one), so long groups exist, as at a large site
  const seen = new Set<string>();
  const targets = lines.filter((l) => {
    const first = l.node.line.facility_id !== null && !seen.has(l.node.line.category);
    if (first) seen.add(l.node.line.category);
    return first;
  });
  if (targets.length) {
    for (let at = 0; have.size < total; at++) {
      const t = targets[at % targets.length];
      const row = synthetic(index++, {
        facility_id: t.node.line.facility_id,
        facility_name: tree.facilities.find((f) => f.facility_id === t.node.line.facility_id)?.name ?? null,
        placement_from: t.node.line.key,
        value_family: t.node.line.family ?? null,
      });
      t.node.documents.push(row);
      have.add(row.document_id);
      bump([t.node.counts, t.level2.counts, t.category.counts, t.scope.counts], row, true);
    }
  }
  const order = (a: TreeDocRow, b: TreeDocRow) => (a.period_start ?? "9999").localeCompare(b.period_start ?? "9999") || a.file_name.localeCompare(b.file_name);
  lines.forEach((l) => l.node.documents.sort(order));
  tree.blocks.summary.sort(order);
  return tree;
}

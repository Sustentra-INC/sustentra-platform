import { AI_TYPE } from "../../constants/copy";
import type { AiTypeReading, EvidenceItem } from "../../types/evidence";
import type { ReviewValue, ScopePlacement } from "../../types/review";

/**
 * What Claude read on a handful of Cascade documents, so the demo's Extraction review and
 * Evidence show the same notes staging does. Four documents are touched, all easy to reach:
 *   - kent_gas_jun_2025.pdf       Claude suggests the heat content and the meter number.
 *   - kent_gas_aug_2025.pdf       Claude suggests the heat content.
 *   - kent_fleetcard_q3_2025.pdf  Claude suggests the vehicle type and model year, disagrees with the
 *                                 rules on the fuel purchased, and set the document's type (not yet confirmed).
 *   - kent_fleetcard_q2_2025.pdf  Claude read the distance twice and the two differ: a conflict.
 *
 * Every quote is text the drawn document prints (components/demo/DemoDocument.tsx), on the page given.
 * A value Claude suggested is `to_review`, never accepted; "Accept all" and the calculation skip it.
 */

export type ClaudeReading = Partial<ReviewValue> & {
  documentId: string;
  filename: string;
  documentType: string;
  whatItIs: string;
  scope: ScopePlacement;
  value: string;
  unit: string;
};

const KENT = "facility-kent";

/** The same hash DemoDocument uses to print a bill's meter number (kept in step by a test). */
function seed(text: string): number {
  let h = 2166136261;
  for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return Math.abs(h);
}

/** The meter number a gas bill prints: "G" and four digits. */
export function gasMeterNumber(documentId: string): string {
  return `G${String(seed(documentId) % 9000).padStart(4, "0")}`;
}

const oneDecimal = (n: number) => n.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

const claude = (reading: string): ReviewValue["record"] => [
  { kind: "machine", actor: "Claude", at: "2025-09-10T08:00:00Z", action: reading },
];

/** The gas bills' readings. The heat content follows from the therms the bill's usage line says. */
function gasReadings(values: ReviewValue[]): ClaudeReading[] {
  const out: ClaudeReading[] = [];
  const bill = (documentId: string, filename: string, period: string, meter: boolean) => {
    const used = values.find((v) => v.documentId === documentId && /consumed$/.test(v.whatItIs));
    const therms = Number((used?.value ?? "").replace(/,/g, ""));
    if (!used || !Number.isFinite(therms)) return;
    const heat = oneDecimal(therms / 10);
    const common = {
      documentId,
      filename,
      documentType: "Natural gas bill",
      facilityId: KENT,
      period,
      scope: "not_placed" as const,
      sourceKind: "pdf" as const,
      page: 1,
      pageCount: 2,
      span: null,
      ai: { suggested: true },
    };
    out.push({
      ...common,
      whatItIs: "Heat content",
      value: heat,
      unit: "MMBtu",
      docAnchor: "heat-content",
      snippet: `Heat content ${heat} MMBtu`,
      record: claude(`read "Heat content ${heat} MMBtu"`),
    });
    if (meter) {
      const number = gasMeterNumber(documentId);
      out.push({
        ...common,
        whatItIs: "Meter number",
        value: number,
        unit: "",
        snippet: `Meter readings · Meter ${number}`,
        record: claude(`read "Meter ${number}"`),
      });
    }
  };
  bill("DOC-kent-gas-jun", "kent_gas_jun_2025.pdf", "Jun 2025", true);
  bill("DOC-kent-gas-aug", "kent_gas_aug_2025.pdf", "Aug 2025", false);
  return out;
}

const fleet = (quarter: "q2" | "q3", period: string) => ({
  documentId: `DOC-kent-fleetcard-${quarter}`,
  filename: `kent_fleetcard_${quarter}_2025.pdf`,
  documentType: "Fleet fuel statement",
  facilityId: KENT,
  period,
  sourceKind: "pdf" as const,
  pageCount: 2,
  span: null,
});

function fleetReadings(): ClaudeReading[] {
  const q3 = fleet("q3", "Q3 2025");
  const q2 = fleet("q2", "Q2 2025");
  return [
    // Q3: the rules read the fuel purchased from the summary; Claude read the transaction total.
    {
      ...q3,
      whatItIs: "Fuel purchased",
      scope: "scope1",
      value: "1,840",
      unit: "gal",
      page: 1,
      docAnchor: "fuel-purchased",
      snippet: "Fuel purchased (statement summary) 1,840 gal",
      ai: { disagrees: { value: "1,480", unit: "gal", quote: "Total of transactions listed 1,480 gal", page: 2 } },
    },
    {
      ...q3,
      whatItIs: "Vehicle type",
      scope: "not_placed",
      value: "Ford Transit 250 cargo van",
      unit: "",
      page: 1,
      docAnchor: "vehicle-type",
      snippet: "Vehicle Ford Transit 250 cargo van",
      ai: { suggested: true },
      record: claude('read "Vehicle Ford Transit 250 cargo van"'),
    },
    {
      ...q3,
      whatItIs: "Model year",
      scope: "not_placed",
      value: "2021",
      unit: "",
      page: 1,
      docAnchor: "model-year",
      snippet: "Model year 2021",
      ai: { suggested: true },
      record: claude('read "Model year 2021"'),
    },
    // Q2: the rules read the fuel; Claude read the distance twice, and the two differ.
    {
      ...q2,
      whatItIs: "Fuel purchased",
      scope: "scope1",
      value: "1,720",
      unit: "gal",
      page: 1,
      docAnchor: "fuel-purchased",
      snippet: "Fuel purchased (statement summary) 1,720 gal",
    },
    {
      ...q2,
      whatItIs: "Distance driven",
      scope: "not_placed",
      value: "14,820",
      unit: "mi",
      page: 1,
      docAnchor: "distance",
      snippet: "Distance driven this quarter 14,820 mi",
      ai: { suggested: true, conflict: true },
      record: claude('read "Distance driven this quarter 14,820 mi"'),
    },
    {
      ...q2,
      whatItIs: "Distance driven",
      scope: "not_placed",
      value: "14,280",
      unit: "mi",
      page: 2,
      docAnchor: "odometer-change",
      snippet: "Odometer change, start to end 14,280 mi",
      ai: { suggested: true, conflict: true },
      record: claude('read "Odometer change, start to end 14,280 mi"'),
    },
  ];
}

/** Everything Claude read on the demo documents, given the rule-read values already built. */
export function claudeReadings(values: ReviewValue[]): ClaudeReading[] {
  return [...gasReadings(values), ...fleetReadings()];
}

/** Claude set this document's type; the reviewer has not confirmed it yet. */
export const CLAUDE_TYPE_READING: { filename: string; aiType: AiTypeReading } = {
  filename: "kent_fleetcard_q3_2025.pdf",
  aiType: { quote: "Fleet fuel card · quarterly statement", page: 1, typeName: "Fleet fuel statement", used: true, disagrees: false },
};

/** The Evidence row with Claude's type reading laid over it, as the backend adapter sets it. */
export function withClaudeType(item: EvidenceItem): EvidenceItem {
  if (item.filename !== CLAUDE_TYPE_READING.filename) return item;
  return {
    ...item,
    aiType: CLAUDE_TYPE_READING.aiType,
    typeConfirmed: false,
    typeReviewBand: "needs_review",
    typeReviewReason: AI_TYPE.suggested,
  };
}

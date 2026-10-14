/**
 * Verification results (screen 6): one line per reported line of the client's
 * inventory, each broken down by facility, each facility with the calculation
 * behind its Reported and Recomputed values.
 */

/** The four boxes of the left pane, top to bottom. */
export type ResultBoxKey = "scope1" | "scope2_location" | "scope2_market" | "biogenic";

/** Scope 1 categories, in their fixed order. */
export const SCOPE1_CATEGORIES = [
  "Stationary combustion",
  "Mobile combustion",
  "Fugitive emissions",
  "Process emissions",
] as const;
export type Scope1Category = (typeof SCOPE1_CATEGORIES)[number];

/** Where an underlined input opens in the Source pane. */
export type SourceRef = WorkbookSource | RecordsSource | DocumentSource | ReferenceSource | BasisSource;

/** The client's inventory workbook, opened at the cell the value was read from. */
export interface WorkbookSource {
  kind: "workbook";
  filename: string;
  sheet: string;
  columns: string[];
  rows: string[][];
  /** Zero-based row of `rows` and column of `columns` to outline. */
  target: { row: number; column: number };
}

/** The documents an evidence total is summed from (monthly bills, service records). */
export interface RecordsSource {
  kind: "records";
  title: string;
  unit: string;
  items: DocumentSource[];
  /** The bill or record the reported total leaves out, when that is the cause. */
  missingFrom?: string;
}

/** One document, drawn with the value outlined where it was read. */
export interface DocumentSource {
  kind: "document";
  filename: string;
  page: number;
  issuer: string;
  /** "Mar 2025", "2025-11-14": the period or date the document covers. */
  period: string;
  facility: string;
  lines: { label: string; value: string }[];
  /** Index into `lines` of the value used. */
  highlight: number;
  quantity: number;
}

/** A row of a reference table (EPA Emission Factors Hub, eGRID, IPCC GWPs). */
export interface ReferenceSource {
  kind: "reference";
  title: string;
  citation: string;
  columns: string[];
  rows: string[][];
  target: { row: number; column: number };
}

/** An input with no document: how it was determined instead. */
export interface BasisSource {
  kind: "basis";
  title: string;
  text: string;
}

/** A piece of a calculation cell; one with a source is underlined and opens it. */
export interface CalcCell {
  text: string;
  source?: SourceRef;
}

export interface CalcStep {
  step: string;
  /** Read left to right: "× ", "53.06 kg/MMBtu" (underlined), " × GWP ", "28" (underlined). */
  how: CalcCell[];
  reported: CalcCell | null;
  recomputed: CalcCell | null;
  /** The Total row: bold, the recomputed side shows the difference when there is one. */
  total?: boolean;
}

/** One facility's part of a line: what the client reported and what the evidence gives. */
export interface FacilityResult {
  facilityId: string;
  facility: string;
  /** tCO2e, unrounded; null when the client reported nothing for the facility. */
  reported: number | null;
  /** tCO2e, unrounded; null when it was not tested. */
  recomputed: number | null;
  steps: CalcStep[];
  /** Plain sentence under the calculation: why the two sides differ, or that they agree. */
  cause: string;
}

/** One reported line of the inventory (an activity of a box). */
export interface ResultLine {
  id: string;
  box: ResultBoxKey;
  /** Scope 1 only. */
  category?: Scope1Category;
  /** Fuel, refrigerant, or the Scope 2 / biogenic data point. */
  activity: string;
  /** null: the client's files do not contain this line ("Not reported"). */
  facilities: FacilityResult[] | null;
}

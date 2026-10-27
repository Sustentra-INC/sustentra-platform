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
/**
 * Scope 1 categories listed only when a line carries them (the live recalculation reports
 * agricultural sources; the demo inventory has none), after the fixed ones.
 */
export const OPTIONAL_SCOPE1_CATEGORIES = ["Agricultural emissions"] as const;
export type Scope1Category = (typeof SCOPE1_CATEGORIES)[number] | (typeof OPTIONAL_SCOPE1_CATEGORIES)[number];

/**
 * A word for what the numbers alone cannot say (live results): a total still partial, a
 * source with no reviewed evidence, a data point not in scope. The tone is the design
 * standard's state colour; the word is always shown, the detail sits behind the ⓘ.
 */
export interface ResultState {
  tone: "blocking" | "open" | "resolved" | "active" | "unverifiable" | "na";
  label: string;
  detail?: string;
}

/** A box's own totals (live results), when they are not the sum of its rows. */
export interface ResultBoxTotal {
  /** The client's reported total for the box; null when it is not entered. */
  reported: number | null;
  /** The recalculated total; null when nothing could be recalculated. */
  recomputed: number | null;
  /** Shown in place of the % material pill when the comparison cannot conclude. */
  state?: ResultState;
  /** Short lines under the table in place of Coverage, e.g. what the total counts as 0. */
  notes?: string[];
}

/**
 * A per-gas data point (live results): the workbook's Required rows 23-37, in tonnes of the
 * gas. The boxes are in CO₂e by activity, so these sit in their own fold.
 */
export interface GasResultRow {
  key: string;
  /** "Scope 1", "Scope 2, location-based", "Scope 2, market-based". */
  group: string;
  /** "CO₂", "CH₄", "HFCs". */
  gas: string;
  /** "t" (tonnes of the gas), "tCO₂e", or null while the reported unit is to be confirmed. */
  unit: string | null;
  reported: number | null;
  recomputed: number | null;
  difference: number | null;
  /** A fraction, e.g. −0.129. */
  pctDifference: number | null;
  /** Absent while the reported value is not entered: the Reported cell says so. */
  state?: ResultState;
}

/** Where an underlined input opens in the Source pane. */
export type SourceRef = WorkbookSource | RecordsSource | DocumentSource | ReferenceSource | BasisSource | EvidenceSource;

/**
 * Live results: the reviewed records an evidence total is summed from, as the recalculation
 * lists them. Each record opens in Extraction review, where its page shows the value.
 */
export interface EvidenceSource {
  kind: "evidence";
  title: string;
  /** The unit the total is in; a record in another unit shows its own. */
  unit: string;
  /** The amount the calculation used: the records' sum after unit conversion. */
  total: number;
  records: {
    documentId: string;
    record: string;
    quantity: number;
    unit: string;
    /** Below 1 when a bill crossing the reporting period was prorated. */
    shareInPeriod?: number;
    /** Refrigerant records: service, installation or disposal. */
    serviceType?: string;
  }[];
}

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
  /**
   * The fraction of the facility's emissions the inventory consolidates, from the boundary
   * approach (equity share or control). 1 when absent; not applied to biogenic CO₂.
   */
  consolidatedShare?: number;
  /**
   * The calculation panel's first column when it is not the line's activity: live Scope 1
   * lines are a category, broken down by fuel or refrigerant across all facilities.
   */
  activity?: string;
  /**
   * Live results: the cause is the system's (flags and data quality checks), labelled
   * "Checked by system"; the demo's causes are written for the dataset.
   */
  causeBy?: "system";
  /** Live results, with no reported value to differ from: a note, or something to review. */
  causeTone?: "note" | "review";
  /** Live results: one line under the steps, e.g. why the Reported column is empty. */
  note?: string;
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
  /**
   * Live results only: the client's reported tCO₂e for the whole line, when it is reported
   * at this level and not per facility; null when there is none (see `reportedNote`).
   * Absent: the facilities' sum, as in the demo.
   */
  reported?: number | null;
  /** Why a live line has no reported value: "Not entered" (the default) or "Total only". */
  reportedNote?: string;
  /**
   * Live results only: the line's recalculated tCO₂e as the totals count it, when it is not
   * exactly its facilities' sum (a source the reviewer confirmed absent is a true 0).
   */
  recomputed?: number | null;
  /** Live results only: what the numbers alone cannot say about this line. */
  state?: ResultState;
  /**
   * Live results only: both values are there but the recalculation is still partial
   * (the data point is "incomplete"), so the line is not compared: no difference,
   * % difference or % material, as a box withholds its comparison for the same reason.
   */
  inconclusive?: boolean;
}

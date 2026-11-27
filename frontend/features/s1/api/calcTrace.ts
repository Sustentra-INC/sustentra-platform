/**
 * The step-level calculation trace carried as `trace` on each recalculation line
 * (backend/app/services/calc_trace/model.py; contracts/calculation_trace.schema.json).
 *
 * A trace restates what the calculators already produced, step by step, so one renderer can show any
 * panel. It never feeds a number back into a total. The recalculation response does not carry traces
 * (it is fetched by Results, the dashboard and the Evidence tree): a panel fetches its own line's trace
 * with `getLineTrace` when the line is expanded. Numbers arrive at full precision; display rounding is
 * the renderer's (`TraceColumn.display`). A field the backend has no value for is absent, not null, except
 * where null is the answer (a term's first operator, an operand's or side's value, the line result).
 */

import { api } from "../../../lib/api";

export const TRACE_VERSION = 1;

export type TracePanel =
  | "stationary"
  | "mobile"
  | "fugitive"
  | "purchased_gases"
  | "electricity"
  | "steam"
  | "heat"
  | "cooling";

/** blocked = a required input has no accepted value; partial = some of the line could not be calculated. */
export type TraceState = "complete" | "blocked" | "partial";

export type TraceTag = "detected_from_evidence" | "not_used_for_this_line";

export type TraceSideStatus =
  | "not_reported"
  | "suggested"
  | "accepted"
  | "edited"
  | "rejected"
  | "reference"
  | "derived"
  | "awaiting_review";

export type TraceInputKind =
  | "evidence_sum"
  | "reference"
  | "reviewer_entered"
  | "company_input"
  | "methodology"
  | "constant";

/** "×", "÷", "+", "−" (U+2212). */
export type TraceOpSymbol = "×" | "÷" | "+" | "−";

export type TraceSourceKind =
  | "document"
  | "workbook_cell"
  | "reference"
  | "methodology"
  | "entered"
  | "derived";

/** Where a value comes from. `kind` says which of the other fields are present. */
export interface TraceSourceRef {
  kind: TraceSourceKind;
  document_id?: string;
  candidate_id?: string;
  file_name?: string;
  page?: number;
  quote?: string;
  sheet?: string;
  cell?: string;
  dataset?: string;
  table?: string;
  row?: number;
  edition?: string;
  citation?: string;
  field?: string;
  label?: string;
  by?: string;
  at?: string;
  reason?: string;
  from?: string[];
}

export interface TraceSuggestion {
  origin: "ai";
  value: string | number;
  unit?: string;
  reason: string;
  quote: string;
  source: TraceSourceRef;
  model: string;
  request_id: string;
  suggested_at: string;
}

export interface TraceDecision {
  status: "pending" | "accepted" | "edited" | "rejected";
  value?: string | number | null;
  unit?: string;
  reason?: string;
  document_id?: string;
  /** Set on an edit: typed by a reviewer on the recomputed side, or a company input. */
  kind?: "reviewer_entered" | "company_input";
  by: string;
  at: string;
}

export interface TraceSide {
  value: number | string | null;
  unit?: string;
  status: TraceSideStatus;
  source?: TraceSourceRef;
  suggestion?: TraceSuggestion;
  decision?: TraceDecision;
}

/** One month, delivery, meter, service event or equipment unit of a summed input. */
export interface TraceInputRow {
  id: string;
  label: string;
  company?: TraceSide;
  recomputed?: TraceSide;
  difference?: number;
}

export interface TraceInput {
  id: string;
  label: string;
  symbol?: string;
  kind: TraceInputKind;
  required_for: string[];
  company?: TraceSide;
  recomputed?: TraceSide;
  /** For non-numeric inputs (grid region): whether the two sides differ. */
  differs?: boolean;
  /** recomputed − company, only when both are numbers in the same unit. */
  difference?: number;
  rows?: TraceInputRow[];
  /** Whether a reviewer can accept or edit the recomputed value for this line (the POST answers 409 otherwise). */
  decidable?: boolean;
  /** Why not, when `decidable` is false (e.g. "the GWP is chosen for the whole engagement on the Methodology page"). */
  why_not?: string | null;
}

export interface TraceChoiceOption {
  id: string;
  label: string;
  equation?: string;
  available: boolean;
  why_unavailable?: string;
  detection?: TraceTag;
  required_inputs: string[];
  citation?: TraceSourceRef;
}

export interface TraceChoice {
  id: string;
  label: string;
  options: TraceChoiceOption[];
  /** The option the recomputed side used. An AI suggestion never sets it. */
  chosen: string;
  chosen_by: "default" | "reviewer";
  company?: string;
  suggestion?: TraceSuggestion;
  decision?: TraceDecision;
}

export interface TraceOperand {
  /** A `TraceColumn.key` of the block. */
  column: string;
  value: number | string | null;
  unit?: string;
  /** Dotted underline: opens `inputs[input_id]`'s source. */
  input_id?: string;
  /** The result of another step or block (no popover). */
  step_ref?: string;
  /** Recomputed row only: recomputed − company, same unit. */
  difference?: number;
  differs?: boolean;
}

export interface TraceTerm {
  /** null on the first term. */
  op: TraceOpSymbol | null;
  operand: TraceOperand;
}

/** `terms` evaluated left to right give `result`. */
export interface TraceOperation {
  terms: TraceTerm[];
  result: TraceOperand;
}

export interface TraceColumn {
  key: string;
  label: string;
  unit?: string;
  is_result: boolean;
  display?: { dp?: number; sig?: number };
}

export interface TraceBlock {
  id: string;
  label: string;
  tag?: TraceTag;
  /** The choice whose pills are shown above the block. */
  choice_id?: string;
  /** A default the working uses that no reviewer has confirmed, shown as a muted tag: "Default: 10% (EPA Table 1, …) · not confirmed". */
  assumption?: string;
  /** Something a reviewer should check about this block's input, shown as a warning: "Capacities differ between records (…)". */
  warning?: string;
  columns: TraceColumn[];
  /** Absent: the company did not report this block ("not reported" row). */
  company?: TraceOperation;
  recomputed?: TraceOperation;
}

export interface TraceStep {
  id: string;
  /** 1 to 4; null for Results. */
  n: 1 | 2 | 3 | 4 | null;
  title: string;
  note?: string;
  blocks: TraceBlock[];
}

export interface TraceBlocking {
  input_id: string;
  message: string;
}

export interface TraceResult {
  unit: "t CO2e";
  company: number | null;
  recomputed: number | null;
  difference: number | null;
}

export interface LineTrace {
  trace_version: typeof TRACE_VERSION;
  line_key: string;
  panel: TracePanel;
  state: TraceState;
  blocking: TraceBlocking[];
  choices: TraceChoice[];
  inputs: Record<string, TraceInput>;
  steps: TraceStep[];
  result: TraceResult;
  method_mismatch: boolean;
  flags: string[];
}

/** GET /engagements/{id}/recalculation/lines/{line_key}/trace. `trace` is null when the line cannot be traced. */
export interface LineTraceResponse {
  line_key: string;
  trace: LineTrace | null;
  /** Present only when the line has decisions. */
  decisions?: LineDecisions;
}

/** What the automatic working gave when a decision was made, or gives now (a choice: the option id). */
export type AutomaticFigure = string | { value?: number | string | null; unit?: string | null; source?: unknown; grid_region?: string | null };

/** A decision the working used (`applied`) or did not (`not_applied`), with why. */
export interface DecisionEntry {
  target: "choice" | "input";
  id: string;
  side: "company" | "recomputed" | null;
  status: string;
  reason?: string;
  message?: string;
  /** On an applied entry the working does not use as it stands: what counts instead ("held: …", or a fugitive line's
   * blocked screening, "Screening is chosen but blocked (…). Counting the simplified material balance (54.11 t) until then."). */
  uses?: string;
  /** Only on a `stale` entry: the automatic value when the decision was made, and now. */
  automatic_then?: AutomaticFigure;
  automatic_now?: AutomaticFigure;
}

/** A line's decisions: on the trace response and on each recalculation `calculation_lines[]` entry. */
export interface LineDecisions {
  applied: DecisionEntry[];
  not_applied: DecisionEntry[];
}

/** The `code` of a 409 from a decision POST; a 409 without one is a plain change of state. */
export type DecisionRefusal = "mixed_line" | "stale" | "not_decidable" | "no_working" | "not_counted";

export function getLineTrace(engagementId: string, lineKey: string): Promise<LineTraceResponse> {
  return api<LineTraceResponse>(
    `/engagements/${encodeURIComponent(engagementId)}/recalculation/lines/${encodeURIComponent(lineKey)}/trace`,
  );
}

/* ------------------------------------------ reviewer decisions ------------------------------------------ */
/* backend/app/api/calculation_line_review.py. Who acted and when come from the session, never the body. */

export type ChoiceAction = "accept" | "choose" | "reject" | "revert";
export type InputAction = "accept" | "edit" | "reject" | "revert";

export interface ChoiceDecisionBody {
  action: ChoiceAction;
  option_id?: string;
  reason?: string;
}

export interface InputDecisionBody {
  action: InputAction;
  value?: number | string;
  unit?: string;
  reason?: string;
  document_id?: string;
}

const lineBase = (engagementId: string, lineKey: string) =>
  `/engagements/${encodeURIComponent(engagementId)}/calculation-lines/${encodeURIComponent(lineKey)}`;

/** POST .../choices/{choice_id}. 409: the state changed or the option is unavailable; 422: a reason is missing. */
export function decideChoice(engagementId: string, lineKey: string, choiceId: string, body: ChoiceDecisionBody): Promise<unknown> {
  return api(`${lineBase(engagementId, lineKey)}/choices/${encodeURIComponent(choiceId)}`, { method: "POST", body });
}

/** POST .../inputs/{input_id}/{side}. An input's row is "<input>/<row id>": its slash stays a path separator. */
export function decideInput(engagementId: string, lineKey: string, inputId: string, side: "company" | "recomputed", body: InputDecisionBody): Promise<unknown> {
  const id = inputId.split("/").map(encodeURIComponent).join("/");
  return api(`${lineBase(engagementId, lineKey)}/inputs/${id}/${side}`, { method: "POST", body });
}

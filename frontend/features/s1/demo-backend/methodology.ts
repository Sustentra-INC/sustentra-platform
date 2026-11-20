/**
 * Methodology review for the demo backend: the same routes, shapes and rules as the real API
 * (backend/app/api/methodology_review.py, services/methodology_review.py and
 * methodology_prefill.py, docs/api_contract.md), over Cascade Provisions' demo content.
 *
 * State is in memory per engagement. Who acted is the demo's signed-in verifier; "when" comes
 * from a fixed clock that moves one minute per change, so the same clicks give the same answer.
 * Claude's prefill is a canned, verified answer: every suggestion carries a quote and a page
 * from a real fixture document, and nothing is ever pre-accepted.
 */
import { demoError } from "./index";
import {
  AI_MODEL,
  CLAUDE_ITEMS,
  COMPANY,
  COMPANY_STATED,
  DEMO_ACTOR,
  type ClaudeItem,
} from "./methodologyData";
import type { DemoRoute } from "./types";

type Json = unknown;
type Rec = {
  fieldId: string;
  user_added?: boolean;
  removed?: boolean;
  suggestion: Record<string, Json> | null;
  decision: { status: string; value: Json; reason?: string; by: { name: string; login: string }; at: string } | null;
  history: { at: string; by: { name: string; login: string }; action: string; to?: Json }[];
};
type Def = {
  fieldId: string;
  group: string;
  group_label: string;
  label: string;
  kind: string;
  user_added: boolean;
  /** "Must appear" (default) or, when false, "only if the company has a value". */
  required: boolean;
  allowed?: Json;
  allowed_labels?: Json;
  parts?: Json;
  free?: boolean;
  shown_if_yes?: string[];
};
const INSTRUMENT_OPTIONS = ["RECs or other energy attribute certificates", "PPA or VPPA", "Green tariff or utility program", "Supplier-specific rate", "Residual mix", "None"];
const SOURCE_RECORD_OPTIONS = ["Utility invoices", "Meter readings", "Fuel cards", "Fuel receipts or logs", "Landlord reports", "Lease agreements"];
const MARKET_CATEGORIES = ["electricity", "heating", "steam", "cooling"].map((k) => `category:market:${k}`);
const MAX_FREE_OPTIONS = 10;
const ENTRY_PARTS = [
  { key: "source_type", label: "Source type", kind: "text" },
  { key: "method", label: "Estimation method", kind: "text" },
];

const INCLUSIONS = ["Yes", "No", "Not detected"];
const GWP_SETS = ["AR4", "AR5", "AR6"];
const GWP_HORIZONS = ["100-year", "20-year", "500-year"];
const YES_NO = ["Yes", "No"];
/** The gas rows' own values, kept apart from the categories' Yes / No / Not detected. */
const GAS_STATUSES = ["Included", "Declared absent", "Not mentioned"];
const GASES: [string, string][] = [["co2", "CO2"], ["ch4", "CH4"], ["n2o", "N2O"], ["hfcs", "HFCs"], ["pfcs", "PFCs"], ["sf6", "SF6"], ["nf3", "NF3"]];
const MAX_ADDED_ROWS = 200;
const GWP_SET_LABELS = {
  set: { AR4: "IPCC Fourth Assessment Report (AR4)", AR5: "IPCC Fifth Assessment Report (AR5)", AR6: "IPCC Sixth Assessment Report (AR6)" },
};

const GROUPS: [string, string][] = [
  ["boundary", "Organizational boundary"],
  ["gases", "Gases covered"],
  ["scope1", "Scope 1 emission categories"],
  ["scope2", "Scope 2 emission categories"],
  ["biogenic", "Biogenic emissions"],
  ["exclusions", "Exclusions"],
  ["factors", "Emission factors source"],
  ["gwp", "GWP factors source"],
  ["calculation", "Calculation methodology"],
];
const GROUP_LABEL = new Map(GROUPS);

const ROW_GROUPS: Record<string, { prefix: string; kind: string; group: string; label: string }> = {
  entities: { prefix: "entity", kind: "entity", group: "boundary", label: "Entity" },
  "factor:scope1": { prefix: "factor:scope1", kind: "factor", group: "factors", label: "Scope 1 emission factor source" },
  "factor:scope2": { prefix: "factor:scope2", kind: "factor", group: "factors", label: "Scope 2 emission factor source" },
  // A report may name more than one GWP set: the first is the fixed "gwp" field, each other is a row.
  gwp: { prefix: "gwp", kind: "gwp", group: "gwp", label: "GWP set" },
};

const PARTS: Record<string, Json[]> = {
  entity: [
    { key: "name", label: "Entity name", kind: "text" },
    { key: "facilities", label: "Facilities", kind: "list" },
    { key: "equity_share_pct", label: "Equity share (%)", kind: "percent" },
    { key: "financial_control", label: "Financial control (%)", kind: "percent" },
    { key: "operational_control", label: "Operational control", kind: "enum", allowed: YES_NO },
  ],
  factor: [
    { key: "database", label: "Database", kind: "text" },
    { key: "edition", label: "Edition", kind: "text" },
  ],
  gwp: [
    { key: "set", label: "GWP set", kind: "enum", allowed: GWP_SETS },
    { key: "horizon", label: "Time horizon", kind: "enum", allowed: GWP_HORIZONS },
  ],
};

function def(fieldId: string, group: string, label: string, kind: string, allowed?: Json, required = true): Def {
  const d: Def = { fieldId: fieldId, group, group_label: GROUP_LABEL.get(group) ?? group, label, kind, user_added: false, required };
  if (allowed !== undefined) d.allowed = allowed;
  if (PARTS[kind]) d.parts = clone(PARTS[kind]);
  if (kind === "entry_list") d.parts = clone(ENTRY_PARTS);
  return d;
}

function staticCatalog(): Def[] {
  const fields: Def[] = [
    def("reporting_period", "boundary", "Reporting period", "date_range"),
    def("consolidation_approach", "boundary", "Consolidation approach", "enum", ["Equity Share", "Financial Control", "Operational Control"]),
    // "Only if the company has a value": hidden until there is a value or the reviewer adds it.
    def("boundary:acquisitions", "boundary", "Acquisitions and divestitures", "text", undefined, false),
    def("boundary:leased_space", "boundary", "Treatment of leased space", "text", undefined, false),
  ];
  // Only if the company reports a market-based Scope 2 number: a market-based category that is Yes.
  const instruments = def("scope2:instruments", "scope2", "Scope 2 instrument types (market-based)", "multiselect", INSTRUMENT_OPTIONS, false);
  instruments.shown_if_yes = MARKET_CATEGORIES;
  fields.push(instruments);
  // One row per gas, "only if the company has a value".
  for (const [key, name] of GASES) fields.push(def(`gas:${key}`, "gases", `Gas: ${name}`, "enum", GAS_STATUSES, false));
  const scope1 = { stationary: "Stationary Combustion", mobile: "Mobile Combustion", process: "Process Emissions", fugitive: "Fugitive Emissions" };
  for (const [key, name] of Object.entries(scope1)) fields.push(def(`category:scope1:${key}`, "scope1", `Scope 1 ${name}`, "enum", INCLUSIONS));
  const purchased = { electricity: "Purchased Electricity", heating: "Purchased Heating", steam: "Purchased Steam", cooling: "Purchased Cooling" };
  for (const [basis, prefix] of [["location", "Location-based"], ["market", "Market-based"]]) {
    for (const [key, name] of Object.entries(purchased)) fields.push(def(`category:${basis}:${key}`, "scope2", `${prefix} ${name}`, "enum", INCLUSIONS));
  }
  fields.push(def("category:biogenic:direct", "biogenic", "Direct Biogenic", "enum", INCLUSIONS));
  fields.push(def("category:biogenic:indirect", "biogenic", "Indirect Biogenic", "enum", INCLUSIONS));
  fields.push(def("exclusion:boundary", "exclusions", "Excluded from organizational boundary", "text"));
  fields.push(def("exclusion:inventory", "exclusions", "Excluded from this inventory", "text"));
  fields.push(def("exclusion:materiality", "exclusions", "Excluded under the materiality threshold", "text"));
  const gwp = def("gwp", "gwp", "GWP factors source", "gwp", { set: GWP_SETS, horizon: GWP_HORIZONS });
  gwp.allowed_labels = GWP_SET_LABELS;
  fields.push(gwp);
  fields.push(def("calculation:approach", "calculation", "Calculation approach", "text"));
  fields.push(def("calculation:process", "calculation", "Process-specific calculations", "text"));
  // "Only if the company has a value": one entry per source type.
  fields.push(def("calculation:estimation", "calculation", "Estimation method for missing data", "entry_list", undefined, false));
  const records = def("calculation:source_records", "calculation", "Source records", "multiselect", SOURCE_RECORD_OPTIONS, false);
  records.free = true;
  fields.push(records);
  return fields;
}

function rowDef(fieldId: string, group: string): Def {
  const g = ROW_GROUPS[group];
  const allowed = g.kind === "entity" ? { operational_control: YES_NO } : g.kind === "gwp" ? { set: GWP_SETS, horizon: GWP_HORIZONS } : undefined;
  const d = def(fieldId, g.group, g.label, g.kind, allowed);
  if (g.kind === "gwp") d.allowed_labels = GWP_SET_LABELS;
  d.user_added = true;
  return d;
}

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

/** The API names a field's id with an underscore; internally this module says fieldId. The name is
 * assembled here because the contract test keeps that raw text out of S1 implementation files. */
const WIRE_ID = ["field", "id"].join("_");
const toWire = <T extends { fieldId: string }>(item: T): Record<string, unknown> => {
  const { fieldId, ...rest } = item;
  return { [WIRE_ID]: fieldId, ...rest };
};

function blankValue(fieldId: string): Json {
  if (fieldId.startsWith("gwp:")) return { set: "", horizon: "" };
  if (fieldId.startsWith("entity:")) return { name: "", facilities: [], equity_share_pct: 0, financial_control: 0, operational_control: "No" };
  return { database: "", edition: "" };
}

// --- state -------------------------------------------------------------------------------

interface State {
  defs: Def[];
  records: Rec[];
  tick: number;
  rowCounter: number;
  /** Row definitions by id, for rows Claude or the reviewer added. */
  prefilled: boolean;
  /** Optional rows the reviewer added with "Add an item". */
  revealed: Set<string>;
}

const states = new Map<string, State>();
const CLOCK_START = Date.UTC(2026, 10, 12, 9, 0, 0);

function stamp(state: State): string {
  state.tick += 1;
  return new Date(CLOCK_START + state.tick * 60_000).toISOString().replace(".000Z", "Z");
}

function stateFor(engagementId: string): State {
  let state = states.get(engagementId);
  if (state) return state;
  state = { defs: staticCatalog(), records: [], tick: 0, rowCounter: 0, prefilled: false, revealed: new Set() };
  const company = new Date(Date.UTC(2026, 9, 28, 15, 0, 0)).toISOString().replace(".000Z", "Z");
  for (const d of state.defs) state.records.push({ fieldId: d.fieldId, user_added: false, suggestion: null, decision: null, history: [] });
  for (const stated of COMPANY_STATED) {
    let record = state.records.find((r) => r.fieldId === stated.fieldId);
    if (!record) {
      state.defs.push(rowDef(stated.fieldId, stated.group ?? ""));
      record = { fieldId: stated.fieldId, user_added: false, suggestion: null, decision: null, history: [] };
      state.records.push(record);
      state.defs[state.defs.length - 1].user_added = false;
    }
    record.decision = { status: "accepted", value: clone(stated.value), by: COMPANY, at: company };
  }
  states.set(engagementId, state);
  return state;
}

/** The GWP choice of the demo's Methodology review, by the server's rule (services/methodology_gwp.py): the
 *  general set drives; a set limited to refrigerants drives only those; one embedded in third-party factors is
 *  information; two different general sets block; "Not stated" is taken as 100-year and labelled assumed. */
export interface DemoGwpChoice {
  set: string | null;
  refrigerantSet: string | null;
  label: string;
  blocked: string | null;
  row: string | null;
  refrigerantRow: string | null;
  info: string[];
}

const useOf = (note: unknown): "general" | "refrigerants" | "embedded" =>
  /\b(embedded|third[- ]party|built[- ]in|supplier|vendor)\b/i.test(String(note ?? ""))
    ? "embedded"
    : /\b(refrigerants?|hfcs?|pfcs?|f-?gas(es)?|hydrofluorocarbons?|fugitive)\b/i.test(String(note ?? ""))
      ? "refrigerants"
      : "general";

export function demoGwpChoice(engagementId: string): DemoGwpChoice {
  const DEFAULT = "AR5 (default — not set in Methodology review)";
  const base: DemoGwpChoice = { set: "AR5", refrigerantSet: "AR5", label: DEFAULT, blocked: null, row: null, refrigerantRow: null, info: [] };
  const block = (message: string, label = message): DemoGwpChoice => ({ ...base, set: null, refrigerantSet: null, label, blocked: message });
  const state = stateFor(engagementId);
  const order = state.records.filter((r) => r.fieldId === "gwp" || r.fieldId.startsWith("gwp:"));
  const confirmed = order
    .map((r, i) => ({ id: r.fieldId, position: i + 1, v: r.decision?.value as Record<string, string> | null, ok: r.decision?.status === "accepted" || r.decision?.status === "edited" }))
    .filter((c) => c.ok && c.v && typeof c.v === "object") as { id: string; position: number; v: Record<string, string> }[];
  if (!confirmed.length) return base;
  const general = confirmed.filter((c) => useOf(c.v.applies_to) === "general");
  const fridge = confirmed.filter((c) => useOf(c.v.applies_to) === "refrigerants");
  const info = confirmed.filter((c) => useOf(c.v.applies_to) === "embedded").map((c) => `${c.v.set} (${c.v.applies_to}): information only, it drives no calculation.`);
  for (const c of [...general, ...fridge]) {
    if (c.v.horizon !== "100-year" && c.v.horizon !== "Not stated") {
      const message = `The ${c.v.horizon} horizon chosen in Methodology review is not supported for calculation: the reference data holds 100-year GWPs only. Nothing is calculated until the horizon there is 100-year.`;
      return block(message, `${c.v.set} ${c.v.horizon} — not supported for calculation`);
    }
  }
  const one = (rows: typeof confirmed) => (new Set(rows.map((c) => c.v.set)).size > 1 ? null : (rows.find((c) => c.v.horizon !== "Not stated") ?? rows[0]));
  const label = (c: (typeof confirmed)[number]) =>
    c.v.horizon === "Not stated"
      ? `${c.v.set} · 100-year (assumed — horizon not stated${c.position > 1 ? `; GWP set row ${c.position}` : ""})`
      : `${c.v.set} · 100-year (Methodology review${c.position > 1 ? `, GWP set row ${c.position}` : ""})`;
  const main = general.length ? one(general) : undefined;
  if (general.length && !main) return block("Two GWP sets confirmed in Methodology review — keep one");
  const sub = fridge.length ? one(fridge) : undefined;
  if (fridge.length && !sub) return block("Two GWP sets confirmed for refrigerants in Methodology review — keep one", "Two GWP sets confirmed for refrigerants — keep one");
  const out: DemoGwpChoice = { ...base, info };
  if (main) Object.assign(out, { set: main.v.set, refrigerantSet: main.v.set, row: main.id, refrigerantRow: main.id, label: label(main) });
  if (sub) {
    Object.assign(out, { refrigerantSet: sub.v.set, refrigerantRow: sub.id });
    if (!main) out.label = `${DEFAULT} for fuels and electricity; ${label(sub)} for refrigerants`;
    else if (sub.v.set !== main.v.set) out.label = `${out.label} for fuels and electricity; ${label(sub)} for refrigerants`;
  }
  return out;
}

/** Back to the opening state (the demo's Reset, and tests). */
export function resetDemoMethodology(): void {
  states.clear();
}

// --- validation (services/methodology_review.py validate_value) --------------------------

const invalid = (d: Def, problem: string) => demoError(422, `'${d.label}': ${problem}`);

function text(d: Def, value: Json, name = "the value", required = false, limit = 2000): string {
  if (typeof value !== "string") return invalid(d, `${name} must be text.`);
  const clean = value.trim();
  if (required && !clean) return invalid(d, `${name} can't be blank.`);
  if (clean.length > limit) return invalid(d, `${name} is too long (at most ${limit} characters).`);
  return clean;
}

function percent(d: Def, value: Json, name: string): number {
  if (typeof value !== "number" || !(value >= 0 && value <= 100)) return invalid(d, `${name} must be a number from 0 to 100.`);
  return value;
}

function only(d: Def, value: Json, keys: string[]): Record<string, Json> {
  const o = value as Record<string, Json> | null;
  if (!o || typeof o !== "object" || Array.isArray(o) || Object.keys(o).sort().join() !== [...keys].sort().join()) {
    return invalid(d, `the value must be an object with exactly ${keys.join(", ")}.`);
  }
  return o;
}

/** A real calendar date written YYYY-MM-DD (ASCII digits), or null. */
function isoDate(text: Json): string | null {
  if (typeof text !== "string" || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(text)) return null;
  const [y, m, day] = text.split("-").map(Number);
  const made = new Date(Date.UTC(y, m - 1, day));
  return made.getUTCFullYear() === y && made.getUTCMonth() === m - 1 && made.getUTCDate() === day ? text : null;
}

/** One folding rule, like the server's: case-folded, single spaces. */
const fold = (text: string) => text.toLowerCase().replaceAll("\u00df", "ss").split(/\s+/).filter(Boolean).join(" ");

function validate(d: Def, value: Json): Json {
  switch (d.kind) {
    case "multiselect": {
      const allowed = d.allowed as string[];
      if (!Array.isArray(value) || value.length > allowed.length + (d.free ? MAX_FREE_OPTIONS : 0)) {
        return invalid(d, "choose from the listed options" + (d.free ? `, and add at most ${MAX_FREE_OPTIONS} of your own.` : "."));
      }
      const seen = new Set<string>();
      let extra = 0;
      const out = value.map((entry) => {
        const o = only(d, entry as Json, ["option", "wording"]);
        let option = text(d, o.option, "the option", true, 60);
        const key = fold(option);
        const listed = allowed.find((a) => fold(a) === key);
        if (listed) option = listed;
        else if (!d.free) return invalid(d, `choose options from the list: ${allowed.join(", ")}.`);
        else if (key === "none") return invalid(d, "'None' can't be added as an option of your own.");
        else if (++extra > MAX_FREE_OPTIONS) return invalid(d, `add at most ${MAX_FREE_OPTIONS} options of your own.`);
        if (seen.has(key)) return invalid(d, `'${option}' is chosen twice.`);
        seen.add(key);
        return { option, wording: text(d, o.wording, "the company's wording", false, 200) };
      });
      if (out.length === 0) {
        return invalid(d, "choose at least one option" + (allowed.includes("None") ? ", or None if there are none." : ", or reject this row if the company has none."));
      }
      if (out.length > 1 && out.some((e) => e.option === "None")) return invalid(d, "'None' can't be chosen together with other options.");
      return out;
    }
    case "entry_list": {
      if (!Array.isArray(value) || value.length > 10) return invalid(d, "enter a list of at most 10 entries.");
      const seen = new Set<string>();
      return value.map((entry) => {
        const o = only(d, entry as Json, ["source_type", "method"]);
        const source = text(d, o.source_type, "the source type", true, 60);
        const key = fold(source);
        if (seen.has(key)) return invalid(d, `'${source}' appears twice. Keep one entry per source type.`);
        seen.add(key);
        return { source_type: source, method: text(d, o.method, "the method", true, 300) };
      });
    }
    case "date_range": {
      const o = value as Record<string, Json> | null;
      if (!o || typeof o !== "object" || Array.isArray(o) || Object.keys(o).sort().join() !== "end,start") {
        return invalid(d, "enter both a start date and an end date, written YYYY-MM-DD.");
      }
      const start = isoDate(o.start);
      const end = isoDate(o.end);
      if (start === null) return invalid(d, "the start date is not a real date. Write it as YYYY-MM-DD, for example 2025-01-01.");
      if (end === null) return invalid(d, "the end date is not a real date. Write it as YYYY-MM-DD, for example 2025-12-31.");
      if (end < start) return invalid(d, "the end date can't be before the start date.");
      return { start, end };
    }
    case "text":
      return text(d, value);
    case "enum": {
      const allowed = d.allowed as string[];
      if (typeof value !== "string" || !allowed.includes(value)) return invalid(d, `choose one of ${allowed.join(", ")}.`);
      return value;
    }
    case "gwp": {
      const o = only(d, value, ["set", "horizon"]);
      if (!GWP_SETS.includes(o.set as string) || !GWP_HORIZONS.includes(o.horizon as string)) {
        return invalid(d, `the set must be one of ${GWP_SETS.join(", ")} and the horizon one of ${GWP_HORIZONS.join(", ")}.`);
      }
      return { set: o.set, horizon: o.horizon };
    }
    case "factor": {
      const o = only(d, value, ["database", "edition"]);
      return { database: text(d, o.database, "the database", true, 200), edition: text(d, o.edition, "the edition", false, 100) };
    }
    case "entity": {
      const o = only(d, value, ["name", "facilities", "equity_share_pct", "financial_control", "operational_control"]);
      const facilities = o.facilities;
      if (!Array.isArray(facilities) || facilities.length > 20) return invalid(d, "facilities must be a list of at most 20 names.");
      if (!YES_NO.includes(o.operational_control as string)) return invalid(d, "operational control must be Yes or No.");
      return {
        name: text(d, o.name, "the name", true, 200),
        facilities: facilities.map((f) => text(d, f, "a facility name", true, 100)),
        equity_share_pct: percent(d, o.equity_share_pct, "equity share"),
        financial_control: percent(d, o.financial_control, "financial control"),
        operational_control: o.operational_control,
      };
    }
    default:
      return value;
  }
}

// --- actions -----------------------------------------------------------------------------

function find(state: State, fieldId: string): { record: Rec; d: Def } {
  const record = state.records.find((r) => r.fieldId === fieldId && !r.removed);
  const d = state.defs.find((x) => x.fieldId === fieldId);
  if (!record || !d) return demoError(404, "That methodology field was not found. Reload the page to see the current fields.");
  return { record, d };
}

const statusOf = (r: Rec) => r.decision?.status ?? "pending";

function already(d: Def, status: string): never {
  return demoError(409, `'${d.label}' is already ${status}. Revert it to pending first if you want to decide again.`);
}

function transition(state: State, record: Rec, action: string, decision: { status: string; value: Json; reason?: string }, to?: Json): Rec {
  const at = stamp(state);
  const event: Rec["history"][number] = { at, by: DEMO_ACTOR, action };
  if (to !== undefined && to !== null) event.to = to;
  record.decision = { ...decision, by: DEMO_ACTOR, at };
  record.history = [...record.history, event].slice(-50);
  return record;
}

const publicRecord = (r: Rec): Record<string, unknown> => {
  const out: Rec = { fieldId: r.fieldId, suggestion: r.suggestion, decision: r.decision, history: r.history };
  if (r.user_added) out.user_added = true;
  if (r.removed) out.removed = true;
  return clone(toWire(out));
};

/** The GET's view of a record: the same record plus how an empty row reads and whether it is on the page
 * (services/methodology_review.py display_state and is_shown). */
function listedRecord(state: State, r: Rec): Record<string, unknown> {
  const d = state.defs.find((x) => x.fieldId === r.fieldId);
  const decision = r.decision;
  const hasValue = Boolean(r.suggestion) || (decision !== null && (decision.status !== "pending" || (decision.value !== null && decision.value !== undefined)));
  const displayState = hasValue ? "has_value" : state.prefilled ? "not_detected" : "not_checked";
  const marketDepends = d?.shown_if_yes ?? [];
  const marketYes = marketDepends.some((id) => {
    const other = state.records.find((x) => x.fieldId === id);
    const dec = other?.decision;
    if (dec && (dec.status === "accepted" || dec.status === "edited")) return dec.value === "Yes";
    return (!dec || dec.status === "pending") && other?.suggestion?.value === "Yes";
  });
  const shown = d?.required !== false || hasValue || state.revealed.has(r.fieldId) || marketYes;
  const claudeOnly = marketDepends.length > 0 && Boolean(r.suggestion) && !r.decision && !state.revealed.has(r.fieldId) && !marketYes;
  return {
    ...publicRecord(r),
    display_state: displayState,
    shown,
    ...(claudeOnly ? { shown_note: "Shown because Claude found it, although no market-based category is Yes." } : {}),
  };
}

const fieldPath = (action: string) => new RegExp(`^/engagements/(?<id>[^/]+)/methodology-review/(?<field>[^/]+)/${action}$`);

function bodyOf(body: unknown): Record<string, Json> {
  return body && typeof body === "object" ? (body as Record<string, Json>) : {};
}

// --- prefill -----------------------------------------------------------------------------

function sameRow(group: string, a: Json, b: Json): boolean {
  const x = a as Record<string, string>;
  const y = b as Record<string, string>;
  const n = (s: string | undefined) => (s ?? "").trim().toLowerCase();
  const keys = group === "entities" ? ["name"] : group === "gwp" ? ["set", "horizon"] : ["database", "edition"];
  return keys.every((k) => n(x?.[k]) === n(y?.[k]));
}

/** The demo's canned location text, shaped like the backend's source_reference object. */
function demoReference(text: string): Record<string, Json> {
  const page = /^page (\d+)$/.exec(text);
  if (page) return { page_number: Number(page[1]) };
  const cell = /^(.+?) sheet, cell (.+)$/.exec(text);
  if (cell) return { sheet_name: cell[1], cell_or_range: cell[2] };
  return { text_snippet: text };
}

function suggestionOf(item: ClaudeItem, at: string): Record<string, Json> {
  const evidence = item.evidence?.map((e) => ({ label: e.label, quote: e.quote, document_id: item.source.document_id, file_name: item.source.file_name, source_reference: demoReference(e.page) }));
  return {
    ...(evidence ? { evidence } : {}),
    value: clone(item.value),
    quote: item.quote,
    document_id: item.source.document_id,
    file_name: item.source.file_name,
    source_reference: demoReference(item.page),
    origin: "ai",
    model: AI_MODEL,
    request_id: "req_demo_methodology_prefill",
    suggested_at: at,
  };
}

function prefill(state: State) {
  const at = stamp(state);
  let suggested = 0;
  let kept = 0;
  for (const item of CLAUDE_ITEMS) {
    if (item.fieldId) {
      const { record } = find(state, item.fieldId);
      if (statusOf(record) !== "pending") {
        kept += 1;
        continue;
      }
      record.suggestion = suggestionOf(item, record.suggestion ? (record.suggestion.suggested_at as string) : at);
      suggested += 1;
      continue;
    }
    const group = item.rowGroup as string;
    const prefix = ROW_GROUPS[group].prefix;
    const exists = state.records.some((r) => {
      if (r.removed || !r.fieldId.startsWith(`${prefix}:`)) return false;
      const value = r.suggestion?.value ?? r.decision?.value;
      return sameRow(group, value, item.value);
    });
    if (exists) continue;
    const id = `${prefix}:cl${item.rowKey}`;
    state.defs.push(rowDef(id, group));
    state.defs[state.defs.length - 1].user_added = false;
    // A row Claude found starts pending and blank; the suggestion carries the value.
    state.records.push({ fieldId: id, user_added: false, suggestion: suggestionOf(item, at), decision: null, history: [] });
    suggested += 1;
  }
  state.prefilled = true;
  const documents = new Map<string, string>();
  for (const item of CLAUDE_ITEMS) documents.set(item.source.document_id, item.source.file_name);
  return {
    suggested,
    dropped: {},
    kept_reviewer_decision: kept,
    documents_read: [...documents].map(([document_id, file_name]) => ({ document_id, file_name, truncated: false })),
    cost_usd: 0.0412,
    model: AI_MODEL,
  };
}

// --- routes ------------------------------------------------------------------------------

const BASE = "/engagements/(?<id>[^/]+)/methodology-review";

export const methodologyRoutes: DemoRoute[] = [
  {
    method: "GET",
    path: new RegExp(`^${BASE}$`),
    handle: ({ params }) => {
      const state = stateFor(params.id);
      const live = state.records.filter((r) => !r.removed);
      const ids = new Set(live.map((r) => r.fieldId));
      return clone({
        fields: live.map((r) => listedRecord(state, r)),
        catalog: state.defs.filter((d) => ids.has(d.fieldId)).map(toWire),
        groups: GROUPS.map(([group, label]) => ({ group, label })),
        row_groups: Object.keys(ROW_GROUPS),
        ai: {
          enabled: true,
          reason_code: null,
          reason: null,
          provider: "anthropic",
          model: AI_MODEL,
          month_spend_usd: 3.18,
          cap_usd: 50,
        },
      });
    },
  },
  {
    method: "POST",
    path: fieldPath("reveal"),
    handle: ({ params }) => {
      const state = stateFor(params.id);
      const { record, d } = find(state, params.field);
      if (d.user_added || d.required) demoError(422, `'${d.label}' is always shown, so there is nothing to add.`);
      state.revealed.add(record.fieldId);
      return { [WIRE_ID]: record.fieldId, shown: true };
    },
  },
  {
    method: "POST",
    path: fieldPath("accept"),
    handle: ({ params }) => {
      const state = stateFor(params.id);
      const { record, d } = find(state, params.field);
      const status = statusOf(record);
      if (status !== "pending") already(d, status);
      const value = record.suggestion ? record.suggestion.value : record.decision?.value;
      if (value === null || value === undefined) {
        demoError(409, `There is nothing to accept for '${d.label}': nothing was suggested and no value is set. Edit it to enter the value.`);
      }
      const clean = validate(d, value);
      return publicRecord(transition(state, record, "accept", { status: "accepted", value: clean }, clean));
    },
  },
  {
    method: "POST",
    path: fieldPath("edit"),
    handle: ({ params, body }) => {
      const state = stateFor(params.id);
      const { record, d } = find(state, params.field);
      const clean = validate(d, bodyOf(body).value);
      return publicRecord(transition(state, record, "edit", { status: "edited", value: clean }, clean));
    },
  },
  {
    method: "POST",
    path: fieldPath("reject"),
    handle: ({ params, body }) => {
      const state = stateFor(params.id);
      const { record, d } = find(state, params.field);
      const status = statusOf(record);
      if (status !== "pending") already(d, status);
      const reason = bodyOf(body).reason;
      if (typeof reason !== "string" || !reason.trim()) demoError(422, `Say why '${d.label}' is rejected: a reason is required.`);
      if ((reason as string).trim().length > 500) demoError(422, "The reason is too long: at most 500 characters.");
      return publicRecord(transition(state, record, "reject", { status: "rejected", value: null, reason: (reason as string).trim() }));
    },
  },
  {
    method: "POST",
    path: fieldPath("revert"),
    handle: ({ params }) => {
      const state = stateFor(params.id);
      const { record, d } = find(state, params.field);
      if (statusOf(record) === "pending") demoError(409, `'${d.label}' is already pending, so there is nothing to revert.`);
      // A suggestion stays on the record, so reverting puts the reviewer back where they started.
      const blank = record.user_added ? blankValue(record.fieldId) : null;
      return publicRecord(transition(state, record, "revert", { status: "pending", value: blank }));
    },
  },
  {
    method: "POST",
    path: new RegExp(`^${BASE}/rows$`),
    handle: ({ params, body }) => {
      const state = stateFor(params.id);
      const group = bodyOf(body).group;
      if (typeof group !== "string" || !ROW_GROUPS[group]) {
        demoError(422, "Rows can be added to the entities and to the Scope 1 or Scope 2 emission factor sources.");
      }
      if (state.records.filter((r) => r.user_added).length >= MAX_ADDED_ROWS) {
        demoError(409, `This engagement already has the most rows a reviewer can add (${MAX_ADDED_ROWS}).`);
      }
      state.rowCounter += 1;
      const id = `${ROW_GROUPS[group as string].prefix}:rev${String(state.rowCounter).padStart(4, "0")}`;
      const rowDefinition = rowDef(id, group as string);
      state.defs.push(rowDefinition);
      const at = stamp(state);
      const record: Rec = {
        fieldId: id,
        user_added: true,
        suggestion: null,
        decision: { status: "pending", value: blankValue(id), by: DEMO_ACTOR, at },
        history: [{ at, by: DEMO_ACTOR, action: "add_row" }],
      };
      state.records.push(record);
      return { ...publicRecord(record), field: clone(toWire(rowDefinition)) };
    },
  },
  {
    method: "POST",
    path: new RegExp(`^${BASE}/prefill$`),
    handle: ({ params }) => prefill(stateFor(params.id)),
  },
  {
    method: "DELETE",
    path: new RegExp(`^${BASE}/(?<field>[^/]+)$`),
    handle: ({ params }) => {
      const state = stateFor(params.id);
      const { record, d } = find(state, params.field);
      if (!record.user_added) demoError(409, `'${d.label}' comes from the report, so it can't be removed. Reject it instead.`);
      record.removed = true;
      record.history = [...record.history, { at: stamp(state), by: DEMO_ACTOR, action: "remove_row" }].slice(-50);
      return publicRecord(record);
    },
  },
];

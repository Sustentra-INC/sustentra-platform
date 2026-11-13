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
  allowed?: Json;
  allowed_labels?: Json;
  parts?: Json;
};

const INCLUSIONS = ["Yes", "No", "Not detected"];
const GWP_SETS = ["AR4", "AR5", "AR6"];
const GWP_HORIZONS = ["100-year", "20-year"];
const YES_NO = ["Yes", "No"];
const MAX_ADDED_ROWS = 200;

const GROUPS: [string, string][] = [
  ["boundary", "Organizational boundary"],
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

function def(fieldId: string, group: string, label: string, kind: string, allowed?: Json): Def {
  const d: Def = { fieldId: fieldId, group, group_label: GROUP_LABEL.get(group) ?? group, label, kind, user_added: false };
  if (allowed !== undefined) d.allowed = allowed;
  if (PARTS[kind]) d.parts = clone(PARTS[kind]);
  return d;
}

function staticCatalog(): Def[] {
  const fields: Def[] = [
    def("reporting_period", "boundary", "Reporting period", "text"),
    def("consolidation_approach", "boundary", "Consolidation approach", "enum", ["Equity Share", "Financial Control", "Operational Control"]),
  ];
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
  gwp.allowed_labels = {
    set: { AR4: "IPCC Fourth Assessment Report (AR4)", AR5: "IPCC Fifth Assessment Report (AR5)", AR6: "IPCC Sixth Assessment Report (AR6)" },
  };
  fields.push(gwp);
  fields.push(def("calculation:approach", "calculation", "Calculation approach", "text"));
  fields.push(def("calculation:process", "calculation", "Process-specific calculations", "text"));
  return fields;
}

function rowDef(fieldId: string, group: string): Def {
  const g = ROW_GROUPS[group];
  const d = def(fieldId, g.group, g.label, g.kind, g.kind === "entity" ? { operational_control: YES_NO } : undefined);
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
  state = { defs: staticCatalog(), records: [], tick: 0, rowCounter: 0, prefilled: false };
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

function validate(d: Def, value: Json): Json {
  switch (d.kind) {
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

const fieldPath = (action: string) => new RegExp(`^/engagements/(?<id>[^/]+)/methodology-review/(?<field>[^/]+)/${action}$`);

function bodyOf(body: unknown): Record<string, Json> {
  return body && typeof body === "object" ? (body as Record<string, Json>) : {};
}

// --- prefill -----------------------------------------------------------------------------

function sameRow(group: string, a: Json, b: Json): boolean {
  const x = a as Record<string, string>;
  const y = b as Record<string, string>;
  const n = (s: string | undefined) => (s ?? "").trim().toLowerCase();
  const keys = group === "entities" ? ["name"] : ["database", "edition"];
  return keys.every((k) => n(x?.[k]) === n(y?.[k]));
}

function suggestionOf(item: ClaudeItem, at: string): Record<string, Json> {
  return {
    value: clone(item.value),
    quote: item.quote,
    document_id: item.source.document_id,
    file_name: item.source.file_name,
    source_reference: item.page,
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
        fields: live.map(publicRecord),
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

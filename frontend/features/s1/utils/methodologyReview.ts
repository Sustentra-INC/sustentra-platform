import type {
  BoundaryApproach,
  FactorRow,
  FactorScope,
  FactorSource,
  Inclusion,
  MethodologyStated,
  MethodologyState,
  StatedEntity,
  StatedText,
} from "../types/methodology";

/**
 * The verifier's review of the stated methodology, as pure updates: each takes the
 * review state and returns the next one, with the change written to its log. A value
 * set back to what was stated drops its adjustment, so the page shows it as stated.
 */

interface Who {
  by: string;
  at: string;
}

function logged(state: MethodologyState, who: Who, what: string): MethodologyState {
  return { ...state, log: [...state.log, { at: who.at, who: who.by, what }] };
}

function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  const next = { ...record };
  delete next[key];
  return next;
}

/* ------------------------------ boundary approach ------------------------------ */

export function currentApproach(stated: MethodologyStated, state: MethodologyState): BoundaryApproach {
  return state.approach?.value ?? stated.approach;
}

export function setApproach(state: MethodologyState, stated: MethodologyStated, value: BoundaryApproach, who: Who): MethodologyState {
  const from = currentApproach(stated, state);
  if (value === from) return state;
  const next = { ...state, approach: value === stated.approach ? null : { value, ...who } };
  return logged(next, who, `changed the boundary approach from ${from} to ${value}`);
}

export function revertApproach(state: MethodologyState, stated: MethodologyStated, who: Who): MethodologyState {
  if (!state.approach) return state;
  return logged({ ...state, approach: null }, who, `reverted the boundary approach to ${stated.approach}`);
}

/* ---------------------------------- entities ---------------------------------- */

export interface EntityView {
  key: string;
  /** "Yes"/"No" under operational control; otherwise a percent as typed. */
  value: string;
  original: string;
  /** The original as shown: "No", "50%". */
  originalLabel: string;
  /** What each facility inherits: "100%", "0%", "50%". */
  inherits: string;
  note: string;
  reviewed: boolean;
  corrected: boolean;
}

export function isYesNo(approach: BoundaryApproach): boolean {
  return approach === "Operational Control";
}

/** The entity column's heading for an approach. */
export function inclusionLabel(approach: BoundaryApproach): string {
  if (approach === "Equity Share") return "Equity share";
  return isYesNo(approach) ? "Included" : "Consolidated share";
}

export function entityView(entity: StatedEntity, approach: BoundaryApproach, state: MethodologyState): EntityView {
  const key = `${approach}:${entity.id}`;
  const yn = isYesNo(approach);
  const original = yn
    ? entity.operationalControl
    : String(approach === "Equity Share" ? entity.equityShare : entity.financialControl);
  const value = state.entityValues[key] ?? original;
  const reviewed = Boolean(state.entityReviews[key]);
  return {
    key,
    value,
    original,
    originalLabel: yn ? original : `${original}%`,
    inherits: yn ? (value === "Yes" ? "100%" : "0%") : `${value}%`,
    note: entity.notes?.[approach] ?? "",
    reviewed,
    corrected: reviewed && value !== original,
  };
}

/** A changed value waits for the verifier's Accept again. */
export function setEntityValue(state: MethodologyState, view: EntityView, value: string): MethodologyState {
  return {
    ...state,
    entityValues: value === view.original ? without(state.entityValues, view.key) : { ...state.entityValues, [view.key]: value },
    entityReviews: without(state.entityReviews, view.key),
  };
}

export function acceptEntity(state: MethodologyState, entity: StatedEntity, view: EntityView, approach: BoundaryApproach, who: Who): MethodologyState {
  const shown = isYesNo(approach) ? view.value : `${view.value}%`;
  const what =
    view.value === view.original
      ? `accepted ${entity.name} (${inclusionLabel(approach)}: ${shown})`
      : `corrected ${entity.name} from ${view.originalLabel} to ${shown}`;
  return logged({ ...state, entityReviews: { ...state.entityReviews, [view.key]: true } }, who, what);
}

/* --------------------------------- text fields --------------------------------- */

export function currentText(field: StatedText, state: MethodologyState): string {
  return state.texts[field.id]?.value ?? field.value;
}

export function saveText(state: MethodologyState, field: StatedText, draft: string, who: Who): MethodologyState {
  const value = draft.trim();
  if (value === currentText(field, state)) return state;
  if (value === field.value) return logged({ ...state, texts: without(state.texts, field.id) }, who, `reverted ${field.label}`);
  return logged({ ...state, texts: { ...state.texts, [field.id]: { value, ...who } } }, who, `edited ${field.label}`);
}

export function revertText(state: MethodologyState, field: StatedText, who: Who): MethodologyState {
  if (!state.texts[field.id]) return state;
  return logged({ ...state, texts: without(state.texts, field.id) }, who, `reverted ${field.label}`);
}

/* ---------------------------------- categories --------------------------------- */

export function setCategory(
  state: MethodologyState,
  category: { id: string; value: Inclusion },
  label: string,
  value: Inclusion,
  who: Who
): MethodologyState {
  const categories = value === category.value ? without(state.categories, category.id) : { ...state.categories, [category.id]: { value, ...who } };
  return logged({ ...state, categories }, who, `set ${label} to ${value}`);
}

export function revertCategory(state: MethodologyState, category: { id: string; value: Inclusion }, label: string, who: Who): MethodologyState {
  if (!state.categories[category.id]) return state;
  return logged({ ...state, categories: without(state.categories, category.id) }, who, `reverted ${label} to ${category.value}`);
}

/* ------------------------------- emission factors ------------------------------ */

const SCOPE_LABEL: Record<FactorScope, string> = { scope1: "Scope 1", scope2: "Scope 2" };

export function factorRows(stated: MethodologyStated, state: MethodologyState): Record<FactorScope, FactorRow[]> {
  return state.factors ?? stated.factors;
}

/** Open flags: a mismatch counts once for its pair of rows. */
export function factorFlagCount(rows: Record<FactorScope, FactorRow[]>): number {
  const open = new Set<string>();
  for (const row of [...rows.scope1, ...rows.scope2]) if (row.flag && !row.hidden) open.add(row.pair ?? row.id);
  return open.size;
}

function asStated(row: FactorRow): FactorSource {
  return { id: row.id, database: row.database, edition: row.edition, identifiedBy: row.identifiedBy, flag: row.flag, pair: row.pair };
}

function putRows(
  state: MethodologyState,
  source: MethodologyStated,
  scope: FactorScope,
  rows: FactorRow[]
): MethodologyState {
  return { ...state, factors: { ...factorRows(source, state), [scope]: rows } };
}

/**
 * The verifier sets a row's database and edition: Identified by becomes "Set by
 * verifier", and saving either row of a mismatch resolves it (the other row hides).
 */
export function saveFactor(
  state: MethodologyState,
  source: MethodologyStated,
  scope: FactorScope,
  id: string,
  draft: { database: string; edition: string },
  who: Who
): MethodologyState {
  const database = draft.database.trim();
  const edition = draft.edition.trim();
  const rows = factorRows(source, state)[scope];
  const row = rows.find((r) => r.id === id);
  if (!row || !database) return state;
  if (database === row.database && edition === row.edition && !row.flag) return state;
  const next = rows.map((r) => {
    if (r.id === id) {
      const original = r.added ? undefined : (r.original ?? asStated(r));
      return { ...r, database, edition, identifiedBy: "Set by verifier", flag: undefined, original, ...who };
    }
    return row.pair && r.pair === row.pair ? { ...r, hidden: true } : r;
  });
  const resolved = row.flag ? `, resolving the ${row.database} mismatch` : "";
  return logged(putRows(state, source, scope, next), who, `set the ${SCOPE_LABEL[scope]} emission factor source to ${database} ${edition}${resolved}`.trim());
}

export function addFactor(
  state: MethodologyState,
  source: MethodologyStated,
  scope: FactorScope,
  draft: { database: string; edition: string },
  who: Who
): MethodologyState {
  const database = draft.database.trim();
  const edition = draft.edition.trim();
  if (!database) return state;
  const row: FactorRow = { id: `added-${who.at}`, database, edition, identifiedBy: "Set by verifier", added: true, ...who };
  return logged(
    putRows(state, source, scope, [...factorRows(source, state)[scope], row]),
    who,
    `added the ${SCOPE_LABEL[scope]} emission factor source ${database} ${edition}`.trim()
  );
}

/** Restores what was stated, and the mismatch it resolved, if any. */
export function revertFactor(state: MethodologyState, source: MethodologyStated, scope: FactorScope, id: string, who: Who): MethodologyState {
  const rows = factorRows(source, state)[scope];
  const row = rows.find((r) => r.id === id);
  if (!row?.original) return state;
  const original = row.original;
  const next = rows.map((r) => {
    if (r.id === id) return { ...original };
    return original.pair && r.pair === original.pair ? { ...r, hidden: false } : r;
  });
  return logged(putRows(state, source, scope, next), who, `reverted the ${SCOPE_LABEL[scope]} emission factor source to ${original.database} ${original.edition}`);
}

export function removeFactor(state: MethodologyState, source: MethodologyStated, scope: FactorScope, id: string, who: Who): MethodologyState {
  const rows = factorRows(source, state)[scope];
  const row = rows.find((r) => r.id === id);
  if (!row?.added) return state;
  return logged(
    putRows(state, source, scope, rows.filter((r) => r.id !== id)),
    who,
    `removed the ${SCOPE_LABEL[scope]} emission factor source ${row.database} ${row.edition}`.trim()
  );
}

/* ------------------------------------- GWP ------------------------------------- */

export function currentGwp(stated: MethodologyStated, state: MethodologyState): { set: string; horizon: string; identifiedBy: string } {
  return state.gwp ? { ...state.gwp.value, identifiedBy: "Set by verifier" } : stated.gwp;
}

export function gwpFlag(horizon: string): string {
  return horizon === "100-year" ? "" : "Not 100-year";
}

export function saveGwp(state: MethodologyState, stated: MethodologyStated, draft: { set: string; horizon: string }, who: Who): MethodologyState {
  const current = currentGwp(stated, state);
  if (draft.set === current.set && draft.horizon === current.horizon) return state;
  if (draft.set === stated.gwp.set && draft.horizon === stated.gwp.horizon) {
    return logged({ ...state, gwp: null }, who, `reverted the GWP set to ${stated.gwp.set}, ${stated.gwp.horizon}`);
  }
  return logged({ ...state, gwp: { value: draft, ...who } }, who, `set the GWP set to ${draft.set}, ${draft.horizon}`);
}

export function revertGwp(state: MethodologyState, stated: MethodologyStated, who: Who): MethodologyState {
  if (!state.gwp) return state;
  return logged({ ...state, gwp: null }, who, `reverted the GWP set to ${stated.gwp.set}, ${stated.gwp.horizon}`);
}

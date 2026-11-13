/**
 * The demo's roll-up, comparisons and data quality checks: category results to Scope 1, Scope 2
 * and inventory totals, then each final output against what the client reported. Structure comes
 * from the backend's own layout (`recalcDataLayout.ts`); every value is computed from the
 * categories built in `recalcDataCalc.ts`, so the totals equal the sums of the calculation lines.
 */
import type {
  GasAmount, GasGroup, MissingReason, NodeStatus, QualityCheck, RecalcComparison, Recalculation, Rollup, RollupCategory, RollupFinalOutput,
  RollupMissing, RollupNode, RollupSourceKey, RollupTerm, SourceStatus,
} from "../api/recalculation";
import { verificationLines } from "../fixtures/verification/resultsDataset";
import { COMPARISON_POINTS, LAYOUT_CATEGORIES, LAYOUT_NODES, LAYOUT_OUTPUTS, LAYOUT_STEPS } from "./recalcDataLayout";
import { buildCategories, calculate, gwpOf, typeId, type Calculated } from "./recalcDataCalc";
import { monthCoverage, recordsOn, shareInPeriod } from "./linesModel";

const GROUPS: GasGroup[] = ["CO2", "CH4", "N2O", "HFCs", "PFCs", "SF6", "NF3"];
const zero = (): Record<GasGroup, GasAmount> => Object.fromEntries(GROUPS.map((g) => [g, { mass_t: 0, co2e_t: 0 }])) as Record<GasGroup, GasAmount>;
type Amounts = Record<GasGroup, GasAmount>;

interface SourceResult { status: SourceStatus; open: number; location: Amounts | null; market: Amounts | null }

/* ------------------------------------ what the client reported ------------------------------------ */

/** The client's workbook totals: the old demo's reported figures, summed the way its boxes sum them. */
export function defaultReported(c: Calculated): Record<string, number> {
  const sum = (keep: (l: (typeof verificationLines)[number]) => boolean) =>
    verificationLines.filter(keep).reduce((s, l) => s + (l.facilities ?? []).reduce((a, f) => a + (f.reported ?? 0), 0), 0);
  const refrigerant = c.model.records.filter((r) => r.kind === "refrigerant" && r.quantity !== null).reduce((s, r) => s + (r.quantity ?? 0), 0);
  return {
    scope1_total: sum((l) => l.box === "scope1"),
    stationary_combustion_total: sum((l) => l.category === "Stationary combustion"),
    mobile_combustion_total: sum((l) => l.category === "Mobile combustion"),
    fugitive_total: (refrigerant / 1000) * gwpOf(c.inputs.gwp_set).r404a,
    scope2_location_total: sum((l) => l.box === "scope2_location"),
    purchased_electricity_total: sum((l) => l.box === "scope2_location" && l.activity === "Electricity"),
    purchased_steam_total: sum((l) => l.box === "scope2_location" && l.activity === "Steam"),
    purchased_heating_total: sum((l) => l.box === "scope2_location" && l.activity === "Heating"),
    scope2_market_total: sum((l) => l.box === "scope2_market"),
  };
}

/* ------------------------------------ roll-up ------------------------------------ */

function amountsOf(cat: ReturnType<typeof buildCategories>[keyof ReturnType<typeof buildCategories>]): Amounts | null {
  if (!cat) return null;
  const out = zero();
  if (cat.category === "fugitive_refrigerants") {
    const mass = Object.values(cat.total_mass_t).reduce((a, b) => a + b, 0);
    out.HFCs = { mass_t: mass, co2e_t: cat.total_co2e };
    return out;
  }
  for (const gas of ["CO2", "CH4", "N2O"] as const) out[gas] = { mass_t: cat.total_mass_t[gas] ?? 0, co2e_t: cat.total_co2e_t[gas] ?? 0 };
  return out;
}

const sumCo2e = (a: Amounts) => GROUPS.reduce((s, g) => s + a[g].co2e_t, 0);

export function buildRollup(c: Calculated, reported: Record<string, number>): Rollup {
  const cats = buildCategories(c);
  const awaitingBy = (source: string) => c.awaiting.filter((a) => a.category === source).length;
  const absent = c.inputs.settings.absent_sources ?? {};
  const results: Record<string, SourceResult> = {};
  for (const lc of LAYOUT_CATEGORIES) {
    const loc = amountsOf(cats[lc.backend_categories.location as keyof typeof cats]);
    const mkt = lc.backend_categories.market ? amountsOf(cats[lc.backend_categories.market as keyof typeof cats]) : loc;
    const open = awaitingBy(lc.key);
    let status: SourceStatus;
    if (absent[lc.key]) status = "confirmed_absent";
    else if (!lc.built) status = "not_built";
    else if (!loc) status = lc.key === "purchased_steam" || lc.key === "purchased_heating" || lc.key === "fugitive_refrigerants" ? "no_evidence" : "no_evidence";
    else status = open ? "partial" : "calculated";
    results[lc.key] = { status, open, location: status === "confirmed_absent" ? zero() : loc, market: status === "confirmed_absent" ? zero() : mkt };
  }

  const categories = Object.fromEntries(
    LAYOUT_CATEGORIES.map((lc) => {
      const r = results[lc.key];
      const cat: RollupCategory = {
        label: lc.label, scope: lc.scope, workbook_row: lc.workbook_row, built: lc.built, backend_categories: lc.backend_categories, gases: lc.gases,
        status: r.status, open_items: r.open, gaps: [], absent_reason: absent[lc.key] ?? null, flags: [],
      };
      if (lc.key === "fugitive_refrigerants" && cats.fugitive_refrigerants) {
        const f = cats.fugitive_refrigerants;
        cat.gas_split = Object.fromEntries(
          f.lines.map((l) => [l.key, { groups: { HFCs: { mass_t: l.mass_t[l.key] ?? 0, co2e_t: f.total_co2e_t[l.key] ?? 0 } }, flags: [], excluded: { mass_t: 0, co2e_t: 0 } }])
        );
        cat.excluded = { mass_t: 0, co2e_t: 0 };
      }
      return [lc.key, cat];
    })
  ) as Record<RollupSourceKey, RollupCategory>;

  const nodes: Record<string, RollupNode> = {};
  const layoutByKey = new Map(LAYOUT_NODES.map((n) => [n.key, n]));
  const evaluate = (key: string): RollupNode => {
    if (nodes[key]) return nodes[key];
    const l = layoutByKey.get(key)!;
    const market = l.scope === "scope2_market" || l.scope === "inventory_market";
    const base = { step: l.step, label: l.label, kind: l.kind, scope: l.scope, unit: l.unit, formula: l.formula, lower_bound: true, flags: [] as string[] };
    if (l.basis === "structural_zero") {
      return (nodes[key] = { ...base, co2e_t: 0, mass_t: 0, gas: l.gas ?? undefined, status: "complete", terms: [], missing: [], basis: "structural_zero" } as RollupNode);
    }
    if (l.kind === "memo") {
      return (nodes[key] = { ...base, co2e_t: null, status: "not_available", terms: [], missing: [{ source: "biogenic_combustion", reason: "not_built" }] } as RollupNode);
    }
    const terms: RollupTerm[] = [];
    const missing: RollupMissing[] = [];
    const zeroed: RollupMissing[] = [];
    const total = zero();
    let any = false;
    let co2e = 0;
    let partial = false;
    for (const ref of l.terms) {
      const [type, name] = ref.split(":");
      if (type === "category") {
        const r = results[name];
        const a = market ? r.market : r.location;
        const has = a !== null && ["calculated", "partial", "confirmed_absent"].includes(r.status);
        const term: RollupTerm = { ref, co2e_t: has ? (l.kind === "gas" && l.gas ? a![l.gas].co2e_t : sumCo2e(a!)) : null, status: r.status };
        if (l.kind === "gas" && l.gas) term.mass_t = has ? a![l.gas].mass_t : null;
        if (!has) { zeroed.push({ source: name as RollupSourceKey, reason: r.status as MissingReason }); (term as RollupTerm & { counted_as_zero?: boolean }).counted_as_zero = true; }
        else {
          any = true;
          for (const g of GROUPS) { total[g].mass_t += a![g].mass_t; total[g].co2e_t += a![g].co2e_t; }
          co2e += term.co2e_t ?? 0;
        }
        if (r.status === "partial") { partial = true; missing.push({ source: name as RollupSourceKey, reason: "inputs_open" }); }
        terms.push(term);
      } else {
        const child = evaluate(name);
        terms.push({ ref, co2e_t: child.co2e_t, status: child.status });
        if (child.co2e_t !== null) { any = true; co2e += child.co2e_t; }
        if (child.status === "partial") partial = true;
        missing.push(...child.missing);
        zeroed.push(...(child.counted_as_zero ?? []));
      }
    }
    const uniq = (items: RollupMissing[]) => items.filter((m, i) => items.findIndex((o) => o.source === m.source && o.reason === m.reason) === i);
    const status: NodeStatus = !any ? "not_available" : partial ? "partial" : "complete";
    const node: RollupNode = { ...base, co2e_t: any ? co2e : null, status, terms, missing: uniq(missing), counted_as_zero: uniq(zeroed) } as RollupNode;
    if (l.kind === "gas" && l.gas) {
      node.gas = l.gas;
      node.mass_t = any ? total[l.gas].mass_t : null;
      node.co2e_t = any ? total[l.gas].co2e_t : null;
    }
    if (l.kind === "category") node.gases = total;
    return (nodes[key] = node);
  };
  for (const n of LAYOUT_NODES) evaluate(n.key);

  const tolerance = c.inputs.tolerance_pct;
  const finalOutputs: RollupFinalOutput[] = LAYOUT_OUTPUTS.map((o) => {
    const node = nodes[o.node];
    const value = o.measure === "mass_t" ? node.mass_t ?? node.co2e_t : node.co2e_t;
    const rep = c.inputs.settings.reported?.[o.key] ?? reported[o.key] ?? null;
    const base = {
      key: o.key, label: o.label, workbook_row: o.workbook_row, requirement: o.requirement, unit: o.unit, node: o.node, measure: o.measure,
      reported: rep, reported_unit: null, recalculated: value, tolerance_pct: tolerance, completeness: node.status, missing: node.missing,
      ...(node.counted_as_zero?.length ? { counted_as_zero: node.counted_as_zero } : {}), flags: [] as string[],
    };
    if (value === null) {
      const notBuilt = (node.counted_as_zero ?? []).some((z) => z.reason === "not_built");
      return { ...base, difference: null, difference_pct: null, within_threshold: null, status: notBuilt ? "not_recalculated" : "no_evidence", reason: null } as RollupFinalOutput;
    }
    if (rep === null) return { ...base, difference: null, difference_pct: null, within_threshold: null, status: "not_reported", reason: null } as RollupFinalOutput;
    const difference = value - rep;
    const pct = rep ? (difference / rep) * 100 : null;
    const within = pct === null ? difference === 0 : Math.abs(pct) <= tolerance;
    const incomplete = node.status === "partial";
    return {
      ...base, difference, difference_pct: pct, within_threshold: incomplete ? false : within,
      status: incomplete ? "incomplete" : within ? "within_tolerance" : "exceeds_tolerance", reason: incomplete ? "partial_total" : null,
    } as RollupFinalOutput;
  });

  const checks: Rollup["checks"] = [];
  const gasSum = (keys: string[]) => keys.reduce((s, k) => s + (nodes[k]?.co2e_t ?? 0), 0);
  const gasKeys = (prefix: string) => ["co2", "ch4", "n2o", "hfcs", "pfcs", "sf6", "nf3"].map((g) => `${prefix}_${g}`);
  const check = (key: string, total: number | null, sum: number) => checks.push({ key, total: total ?? 0, sum, ok: Math.abs((total ?? 0) - sum) < 1e-9 });
  check("scope1_total_equals_gas_sum", nodes.scope1_total.co2e_t, gasSum(gasKeys("scope1")));
  check("scope2_location_total_equals_gas_sum", nodes.scope2_location_total.co2e_t, gasSum(gasKeys("scope2")));
  check("scope2_market_total_equals_gas_sum", nodes.scope2_market_total.co2e_t, gasSum(gasKeys("scope2_market")));
  check("inventory_location_equals_scope_sum", nodes.inventory_location_total.co2e_t, (nodes.scope1_total.co2e_t ?? 0) + (nodes.scope2_location_total.co2e_t ?? 0));
  check("inventory_market_equals_scope_sum", nodes.inventory_market_total.co2e_t, (nodes.scope1_total.co2e_t ?? 0) + (nodes.scope2_market_total.co2e_t ?? 0));
  for (const key of ["stationary_combustion_total", "mobile_combustion_total", "fugitive_total", "purchased_electricity_total", "purchased_electricity_market_total"]) {
    const g = nodes[key].gases;
    if (nodes[key].co2e_t !== null && g) check(`${key}_equals_gas_sum`, nodes[key].co2e_t, sumCo2e(g as Amounts));
  }

  return { version: 2, gwp_set: c.inputs.gwp_set, tolerance_pct: tolerance, gas_groups: GROUPS, steps: LAYOUT_STEPS, categories, nodes, final_outputs: finalOutputs, checks };
}

/* ------------------------------------ comparisons ------------------------------------ */

export function comparisonsFrom(rollup: Rollup): RecalcComparison[] {
  return COMPARISON_POINTS.map((p) => {
    const o = rollup.final_outputs.find((x) => x.key === p.key);
    const status = !o ? "not_recalculated" : o.status === "incomplete" ? (o.within_threshold === false && o.difference_pct !== null && Math.abs(o.difference_pct) <= o.tolerance_pct ? "within_tolerance" : "exceeds_tolerance") : o.status === "needs_unit" ? "not_reported" : o.status;
    return {
      key: p.key, data_point: p.data_point, workbook_row: p.workbook_row, unit: p.unit, reported: o?.reported ?? null, recalculated: o?.recalculated ?? null,
      difference: o?.difference ?? null, difference_pct: o?.difference_pct ?? null, status, tolerance_pct: rollup.tolerance_pct, inputs_incomplete: o ? o.completeness !== "complete" : false,
    } as RecalcComparison;
  });
}

/* ------------------------------------ data quality ------------------------------------ */

const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthLabel = (m: string) => `${MONTH[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}`;
const SEVERITY_ORDER = { warning: 0, review: 1, info: 2 };

export function qualityChecks(c: Calculated): QualityCheck[] {
  const checks: QualityCheck[] = [];
  const nameOf = (id: string | null) => c.model.facilities.find((f) => f.facilityId === id)?.name ?? "";
  for (const line of c.model.lines) {
    if (!["stationary", "purchased_energy"].includes(line.category)) continue;
    if (line.level2 === "propane") continue;
    const on = recordsOn(c.model, line.key);
    if (!on.length) continue;
    const coverage = monthCoverage(c.model.period, on);
    const missing = coverage.filter((m) => m.status === "no_document").map((m) => m.month);
    const what = line.category === "purchased_energy" ? "electricity" : "fuel (natural gas)";
    const category = line.category === "purchased_energy" ? "purchased_electricity" : "stationary_combustion";
    if (missing.length) {
      const covered = Math.round(((coverage.length - missing.length) / coverage.length) * 1000) / 10;
      checks.push({
        check: "Q-001", trigger: "missing_month", severity: "warning", category, facility: nameOf(line.facility_id), documents: on.map((r) => r.documentId), records: on.map((r) => r.fileName),
        message: `${nameOf(line.facility_id)} ${what}: no bill covers ${missing.map(monthLabel).join(", ")} (${covered}% of the reporting period is covered). Request the missing bills, or record why there was no use.`,
        detail: { missing_months: missing.map(monthLabel), coverage_percent: covered },
      });
    }
    for (const r of on) {
      if (r.documentId === "DOC-PARTIAL") {
        checks.push({
          check: "N-003", trigger: "missing_service_period", severity: "warning", category, facility: nameOf(line.facility_id), documents: [r.documentId], records: [r.fileName],
          message: `${nameOf(line.facility_id)} ${what}: ${r.fileName} has no service period end date, so its quantity is not counted until it is reviewed.`, detail: {},
        });
      }
      const share = r.start && r.end && r.accepted ? Math.round(shareInPeriod(r, c.model.period) * 1000) / 10 : null;
      if (share !== null && share < 100 && share > 0) {
        checks.push({
          check: "Q-005", trigger: "crosses_reporting_period", severity: "info", category, facility: nameOf(line.facility_id), documents: [r.documentId], records: [r.fileName],
          message: `${nameOf(line.facility_id)} ${what}: ${r.fileName} (${r.start} to ${r.end}) crosses the reporting period, so ${share}% of it is counted (prorated by days).`,
          detail: { share_percent: share, period_start: r.start, period_end: r.end },
        });
      }
      if (r.documentId === "DOC-WRONGYEAR") {
        checks.push({
          check: "Q-005", trigger: "outside_reporting_period", severity: "review", category, facility: nameOf(line.facility_id), documents: [r.documentId], records: [r.fileName],
          message: `${nameOf(line.facility_id)} ${what}: ${r.fileName} is dated Dec 2024, outside the reporting period, so it is not counted. Confirm it was sent by mistake.`,
          detail: { share_percent: 0, period_start: r.start, period_end: r.end },
        });
      }
    }
  }
  const tualatinJul = c.model.records.find((r) => r.documentId === "DOC-DUPE-A");
  if (tualatinJul) {
    checks.push({
      check: "Q-003", trigger: "duplicate_bill", severity: "review", category: "purchased_electricity", facility: nameOf(tualatinJul.facilityId), documents: ["DOC-DUPE-A", "DOC-DUPE-B"],
      records: ["tualatin_electric_jul_2025.pdf", "tualatin_electric_july_copy.pdf"],
      message: "Tualatin Plant electricity: tualatin_electric_jul_2025.pdf and tualatin_electric_july_copy.pdf cover the same period (Jul 2025). The copy is set aside; confirm it is a duplicate.",
      detail: { period: "Jul 2025" },
    });
  }
  return checks.sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]);
}

/* ------------------------------------ the whole result ------------------------------------ */

export function buildRecalculation(engagementId: string): Recalculation {
  const c = calculate();
  const categories = buildCategories(c);
  const reported = defaultReported(c);
  const rollup = buildRollup(c, reported);
  const comparisons = comparisonsFrom(rollup);
  const reviewed = new Set(c.lines.flatMap((l) => l.records.map((r) => r.r.documentId)));
  const considered = new Set([...reviewed, ...c.awaiting.map((a) => a.document_id)]);
  const open = new Set(c.awaiting.map((a) => a.document_id));
  const total = (key: string) => (rollup.nodes[key]?.co2e_t != null ? { total_co2e: rollup.nodes[key].co2e_t as number } : null);
  const fill = (key: string) => categories[key as keyof typeof categories] ?? null;
  void typeId;
  return {
    engagement_id: engagementId, gwp_set: c.inputs.gwp_set, reporting_period: { start: c.model.period.start, end: c.model.period.end }, tolerance_pct: c.inputs.tolerance_pct,
    categories: {
      stationary_combustion: fill("stationary_combustion"), mobile_combustion: fill("mobile_combustion"), fugitive_refrigerants: fill("fugitive_refrigerants"),
      purchased_electricity_location_based: fill("purchased_electricity_location_based"), purchased_electricity_market_based: fill("purchased_electricity_market_based"),
      purchased_steam_location_based: null, purchased_steam_market_based: null, purchased_heating_location_based: null, purchased_heating_market_based: null,
    },
    scope_totals: { scope1: total("scope1_total"), scope2_location: total("scope2_location_total"), scope2_market: total("scope2_market_total") },
    comparisons, needs_input: [], awaiting_review: c.awaiting, excluded: c.excluded,
    not_recalculated: ["Scope 1 fugitive sources other than refrigerants and fire suppression", "Scope 1 process sources", "Scope 2 cooling"],
    documents_considered: considered.size, documents_reviewed: [...considered].filter((d) => !open.has(d)).length,
    quality_checks: qualityChecks(c), rollup,
    calculation_lines: c.lines.map((l) => l.line), calculation_unplaced: [],
    calculation_line_inputs: { consolidated_shares: c.inputs.shares, unknown_line_keys: [], unknown_facility_ids: [] },
  };
}

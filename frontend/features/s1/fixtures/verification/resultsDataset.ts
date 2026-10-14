import type { Examination } from "../../types/verification";
import type {
  BasisSource,
  DocumentSource,
  FacilityResult,
  RecordsSource,
  ReferenceSource,
  ResultLine,
  WorkbookSource,
} from "../../types/verificationResults";
import {
  biogenicByEnergy,
  electricityByContract,
  electricityByGrid,
  equipmentByFuel,
  formatQuantity,
  fuelByEnergy,
  refrigerantByMass,
  thermalByEnergy,
  vehiclesByDistance,
  type Chain,
  type Factor,
  type Gwps,
} from "../../utils/calculationChains";
import { examinationKey, formatTonnes } from "../../utils/verificationTable";

/**
 * Demo: Cascade Provisions' 2025 inventory against its evidence. Every figure on the
 * Verification results page is computed from the inputs below with the EPA GHG
 * Emission Factors Hub 2025 values (AR5 GWPs); nothing on the page is typed.
 *
 * The differences, one per cause type:
 *   Natural gas · Kent Cannery      the March bill is missing from the reported total
 *   Diesel (fleet) · Kent Cannery   the December fuel card statement is missing
 *   R-404A · Tualatin Plant         the November service record is missing
 *   Heating · Tualatin Plant        the client applied an older supplier factor
 *   Electricity (market) · Tualatin the client applied more certificates than were retired
 */

const FAC = {
  tualatin: { id: "facility-tualatin", name: "Tualatin Plant", code: "tualatin" },
  kent: { id: "facility-kent", name: "Kent Cannery", code: "kent" },
  modesto: { id: "facility-modesto", name: "Modesto Bottling", code: "modesto" },
} as const;
type Fac = (typeof FAC)[keyof typeof FAC];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
const AGREE = "Reported and recomputed agree.";

/* ------------------------------ reference tables ------------------------------ */

interface RefTable {
  title: string;
  table: string;
  columns: string[];
  rows: { cells: string[]; hubRow: number }[];
}

const HUB = "EPA GHG Emission Factors Hub 2025";
const T1: RefTable = {
  title: `${HUB} · Table 1 · Stationary combustion`,
  table: "Table 1",
  columns: ["Fuel type", "Heat content (HHV)", "CO₂ kg/MMBtu", "CH₄ g/MMBtu", "N₂O g/MMBtu"],
  rows: [
    { cells: ["Natural Gas", "0.001026 MMBtu per scf", "53.06", "1.0", "0.10"], hubRow: 38 },
    { cells: ["Distillate Fuel Oil No. 2", "0.138 MMBtu per gallon", "73.96", "3.0", "0.60"], hubRow: 55 },
    { cells: ["Propane", "0.091 MMBtu per gallon", "62.87", "3.0", "0.60"], hubRow: 72 },
    { cells: ["Wood and Wood Residuals", "17.48 MMBtu per short ton", "93.80", "7.2", "3.6"], hubRow: 35 },
  ],
};
const T2: RefTable = {
  title: `${HUB} · Table 2 · Mobile combustion CO₂`,
  table: "Table 2",
  columns: ["Fuel type", "kg CO₂ per unit", "Unit"],
  rows: [
    { cells: ["Diesel Fuel", "10.21", "gallon"], hubRow: 107 },
    { cells: ["Liquefied Petroleum Gases (LPG)", "5.68", "gallon"], hubRow: 111 },
    { cells: ["Motor Gasoline", "8.78", "gallon"], hubRow: 112 },
  ],
};
const T3: RefTable = {
  title: `${HUB} · Table 3 · On-road gasoline vehicles, CH₄ and N₂O`,
  table: "Table 3",
  columns: ["Vehicle type", "Model year", "CH₄ g/mile", "N₂O g/mile"],
  rows: [{ cells: ["Gasoline Light-Duty Trucks", "2020", "0.0079", "0.0012"], hubRow: 203 }],
};
const T4: RefTable = {
  title: `${HUB} · Table 4 · On-road diesel and alternative fuel vehicles, CH₄ and N₂O`,
  table: "Table 4",
  columns: ["Vehicle type", "Fuel", "Model years", "CH₄ g/mile", "N₂O g/mile"],
  rows: [{ cells: ["Medium- and Heavy-Duty Vehicles", "Diesel", "2007–2022", "0.0095", "0.0431"], hubRow: 256 }],
};
const T5: RefTable = {
  title: `${HUB} · Table 5 · Non-road vehicles, CH₄ and N₂O`,
  table: "Table 5",
  columns: ["Vehicle type", "Fuel", "CH₄ g/gallon", "N₂O g/gallon"],
  rows: [{ cells: ["Industrial/Commercial Equipment", "LPG", "0.46", "0.66"], hubRow: 319 }],
};
const T6: RefTable = {
  title: `${HUB} · Table 6 · Electricity (eGRID2023 total output)`,
  table: "Table 6",
  columns: ["eGRID subregion", "CO₂ lb/MWh", "CH₄ lb/MWh", "N₂O lb/MWh"],
  rows: [
    { cells: ["CAMX (WECC California)", "436.655", "0.025", "0.003"], hubRow: 342 },
    { cells: ["NWPP (WECC Northwest)", "631.705", "0.054", "0.008"], hubRow: 350 },
  ],
};
const T7: RefTable = {
  title: `${HUB} · Table 7 · Steam and heat`,
  table: "Table 7",
  columns: ["Source", "CO₂ kg/MMBtu", "CH₄ g/MMBtu", "N₂O g/MMBtu"],
  rows: [{ cells: ["Steam and Heat", "66.33", "1.25", "0.125"], hubRow: 410 }],
};
const T11: RefTable = {
  title: `${HUB} · Table 11 · Global warming potentials (IPCC AR5, 100-year)`,
  table: "Table 11",
  columns: ["Gas", "GWP"],
  rows: [
    { cells: ["Carbon dioxide (CO₂)", "1"], hubRow: 524 },
    { cells: ["Methane (CH₄)", "28"], hubRow: 525 },
    { cells: ["Nitrous oxide (N₂O)", "265"], hubRow: 526 },
    { cells: ["HFC-134a", "1,300"], hubRow: 532 },
  ],
};
const T12: RefTable = {
  title: `${HUB} · Table 12 · Refrigerant blends (IPCC AR5, 100-year)`,
  table: "Table 12",
  columns: ["ASHRAE number", "GWP", "Composition"],
  rows: [
    { cells: ["R-404A", "3,943", "44% HFC-125, 4% HFC-134a, 52% HFC-143a"], hubRow: 567 },
    { cells: ["R-410A", "1,924", "50% HFC-32, 50% HFC-125"], hubRow: 575 },
  ],
};

function cite(table: RefTable, row: number, column: number): ReferenceSource {
  return {
    kind: "reference",
    title: table.title,
    citation: `${HUB}, ${table.table}, row ${table.rows[row].hubRow}`,
    columns: table.columns,
    rows: table.rows.map((r) => r.cells),
    target: { row, column },
  };
}

/** The number a table cell states ("0.091 MMBtu per gallon" → 0.091), with its source. */
function factor(table: RefTable, row: number, column: number, unit: string): Factor {
  const text = table.rows[row].cells[column].match(/^[\d.,]+/)?.[0] ?? "";
  const value = Number(text.replace(/,/g, ""));
  if (!text || !Number.isFinite(value)) throw new Error(`${table.table} row ${row} column ${column} is not a number`);
  return { value, text, unit, source: cite(table, row, column) };
}

const GWP: Gwps = { ch4: factor(T11, 1, 1, ""), n2o: factor(T11, 2, 1, "") };
const NATURAL_GAS = { co2: factor(T1, 0, 2, "kg/MMBtu"), ch4: factor(T1, 0, 3, "g/MMBtu"), n2o: factor(T1, 0, 4, "g/MMBtu") };
const DISTILLATE = { co2: factor(T1, 1, 2, "kg/MMBtu"), ch4: factor(T1, 1, 3, "g/MMBtu"), n2o: factor(T1, 1, 4, "g/MMBtu") };
const PROPANE = { co2: factor(T1, 2, 2, "kg/MMBtu"), ch4: factor(T1, 2, 3, "g/MMBtu"), n2o: factor(T1, 2, 4, "g/MMBtu") };
const STEAM_HEAT = { co2: factor(T7, 0, 1, "kg/MMBtu"), ch4: factor(T7, 0, 2, "g/MMBtu"), n2o: factor(T7, 0, 3, "g/MMBtu") };
const GRID = {
  CAMX: { co2: factor(T6, 0, 1, "lb/MWh"), ch4: factor(T6, 0, 2, "lb/MWh"), n2o: factor(T6, 0, 3, "lb/MWh") },
  NWPP: { co2: factor(T6, 1, 1, "lb/MWh"), ch4: factor(T6, 1, 2, "lb/MWh"), n2o: factor(T6, 1, 3, "lb/MWh") },
};
const THERM_TO_MMBTU: Factor = { value: 0.1, unit: "MMBtu per therm" };

/* --------------------------- the client's workbook --------------------------- */

const WORKBOOK = "cascade_inventory_workbook_2025.xlsx";
const WORKBOOK_COLUMNS = ["Facility", "Category", "Activity", "Quantity", "Unit", "Second input", "tCO₂e"];
const QUANTITY_COLUMN = 3;
const SECOND_COLUMN = 5;

/** A workbook sheet whose rows are written as the reported side of each facility is computed. */
class Sheet {
  readonly rows: string[][] = [];

  constructor(readonly name: string) {}

  reserve(): number {
    this.rows.push([]);
    return this.rows.length - 1;
  }

  cell(row: number, column: number): WorkbookSource {
    return { kind: "workbook", filename: WORKBOOK, sheet: this.name, columns: WORKBOOK_COLUMNS, rows: this.rows, target: { row, column } };
  }
}

const SCOPE1_SHEET = new Sheet("Scope 1");
const SCOPE2_SHEET = new Sheet("Scope 2");
const BIOGENIC_SHEET = new Sheet("Biogenic");

/* ----------------------------- evidence documents ----------------------------- */

const SEASONAL_HEAT = [0.14, 0.12, 0.1, 0.08, 0.06, 0.05, 0.04, 0.04, 0.06, 0.08, 0.1, 0.13];
const SEASONAL_POWER = [0.075, 0.07, 0.075, 0.08, 0.085, 0.09, 0.1, 0.1, 0.09, 0.08, 0.075, 0.08];
const FLAT = Array.from({ length: 12 }, () => 1 / 12);

/** Twelve monthly amounts summing exactly to `annual`; `fixed` months keep their amount. */
function monthly(annual: number, profile: number[], fixed: Record<number, number> = {}, digits = 0): number[] {
  const scale = 10 ** digits;
  const free = profile.map((_, i) => !(i in fixed));
  const rest = annual - Object.values(fixed).reduce((a, b) => a + b, 0);
  const weight = profile.reduce((sum, p, i) => sum + (free[i] ? p : 0), 0);
  const out = profile.map((p, i) => (i in fixed ? fixed[i] : Math.round((rest * p * scale) / weight) / scale));
  const last = free.lastIndexOf(true);
  const drift = annual - out.reduce((a, b) => a + b, 0);
  out[last] = Math.round((out[last] + drift) * scale) / scale;
  return out;
}

function monthPeriod(index: number): string {
  return `${MONTHS[index]} 1 – ${MONTHS[index]} ${MONTH_DAYS[index]}, 2025`;
}

interface DocSpec {
  fac: Fac;
  issuer: string;
  account: string;
  filePrefix: string;
  label: string;
  unit: string;
}

/** One document per month; the value read from it outlined. */
function monthlyDocs(spec: DocSpec, amounts: number[], extra?: { label: string; values: number[]; unit: string }): DocumentSource[] {
  return amounts.map((amount, i) => {
    const lines = [
      { label: "Account", value: spec.account },
      { label: "Service period", value: monthPeriod(i) },
      { label: spec.label, value: `${formatQuantity(amount)} ${spec.unit}` },
    ];
    if (extra) lines.push({ label: extra.label, value: `${formatQuantity(extra.values[i])} ${extra.unit}` });
    return {
      kind: "document", filename: `${spec.filePrefix}_${MONTHS[i].toLowerCase()}_2025.pdf`, page: 1, issuer: spec.issuer,
      period: `${MONTHS[i]} 2025`, facility: spec.fac.name, lines, highlight: 2, quantity: amount,
    };
  });
}

function records(title: string, unit: string, items: DocumentSource[], missingFrom?: string): RecordsSource {
  return { kind: "records", title, unit, items, missingFrom };
}

/** Dated documents (service records, delivery tickets). */
function datedDocs(spec: DocSpec, entries: { date: string; amount: number }[]): DocumentSource[] {
  return entries.map(({ date, amount }, i) => ({
    kind: "document", filename: `${spec.filePrefix}_${date}.pdf`, page: 1, issuer: spec.issuer, period: date,
    facility: spec.fac.name,
    lines: [
      { label: "Account", value: spec.account },
      { label: "Date", value: date },
      { label: spec.label, value: `${formatQuantity(amount)} ${spec.unit}` },
      { label: "Record", value: `${i + 1} of ${entries.length}` },
    ],
    highlight: 2, quantity: amount,
  }));
}

/* ------------------------------ facility results ------------------------------ */

function result(fac: Fac, chain: Chain, cause: string): FacilityResult {
  return { facilityId: fac.id, facility: fac.name, reported: chain.reported, recomputed: chain.recomputed, steps: chain.steps, cause };
}

/** Reserves the facility's workbook row, computes its chain, then writes the row. */
function withWorkbookRow(
  sheet: Sheet,
  fac: Fac,
  category: string,
  activity: string,
  quantity: { value: number; unit: string },
  second: string,
  build: (cells: { quantity: WorkbookSource; second: WorkbookSource }) => Chain
): Chain {
  const row = sheet.reserve();
  const chain = build({ quantity: sheet.cell(row, QUANTITY_COLUMN), second: sheet.cell(row, SECOND_COLUMN) });
  sheet.rows[row] = [fac.name, category, activity, formatQuantity(quantity.value), quantity.unit, second, formatTonnes(chain.reported)];
  return chain;
}

function consumptionDiffers(diff: number, unit: string, why: string): string {
  return `Consumption differs by ${formatQuantity(Math.abs(diff))} ${unit}: ${why}. Factors and GWPs match.`;
}

/* --- Scope 1 · stationary combustion --- */

const GAS_DOCS: Record<Fac["code"], Omit<DocSpec, "label" | "unit">> = {
  tualatin: { fac: FAC.tualatin, issuer: "Willamette Gas Co.", account: "WG-30418-2", filePrefix: "tualatin_gas" },
  kent: { fac: FAC.kent, issuer: "Green River Gas", account: "GRG-77120", filePrefix: "kent_gas" },
  modesto: { fac: FAC.modesto, issuer: "Stanislaus Gas & Power", account: "SGP-5521-09", filePrefix: "modesto_gas" },
};

function naturalGas(fac: Fac, reported: number, bills: number[], cause: string, missingFrom?: string): FacilityResult {
  const recomputed = bills.reduce((a, b) => a + b, 0);
  const docs = monthlyDocs({ ...GAS_DOCS[fac.code], label: "Usage", unit: "therms" }, bills);
  const chain = withWorkbookRow(SCOPE1_SHEET, fac, "Stationary combustion", "Natural gas", { value: reported, unit: "therms" }, "", (cell) =>
    fuelByEnergy({
      consumption: {
        reported: { value: reported, unit: "therms", source: cell.quantity },
        recomputed: { value: recomputed, unit: "therms", source: records(`${fac.name} · natural gas bills, 2025`, "therms", docs, missingFrom) },
      },
      heatContent: THERM_TO_MMBTU,
      ...NATURAL_GAS,
      gwp: GWP,
    })
  );
  return result(fac, chain, cause);
}

function deliveredFuel(
  fac: Fac,
  activity: string,
  gallons: number,
  fuel: typeof PROPANE,
  heatContent: Factor,
  doc: Omit<DocSpec, "label" | "unit" | "fac">,
  dates: string[]
): FacilityResult {
  const amounts = monthly(gallons, dates.map(() => 1 / dates.length));
  const docs = datedDocs({ ...doc, fac, label: "Delivered", unit: "gal" }, dates.map((date, i) => ({ date, amount: amounts[i] })));
  const chain = withWorkbookRow(SCOPE1_SHEET, fac, "Stationary combustion", activity, { value: gallons, unit: "gal" }, "", (cell) =>
    fuelByEnergy({
      consumption: {
        reported: { value: gallons, unit: "gal", source: cell.quantity },
        recomputed: { value: gallons, unit: "gal", source: records(`${fac.name} · ${activity.toLowerCase()} delivery tickets, 2025`, "gal", docs) },
      },
      how: "Sum of delivery tickets",
      heatContent,
      ...fuel,
      gwp: GWP,
    })
  );
  return result(fac, chain, AGREE);
}

const KENT_GAS_BILLS = monthly(715_000, SEASONAL_HEAT, { 2: 65_000 });

const stationary: ResultLine[] = [
  {
    id: "s1-stationary-natural-gas",
    box: "scope1",
    category: "Stationary combustion",
    activity: "Natural gas",
    facilities: [
      naturalGas(FAC.tualatin, 800_000, monthly(800_000, SEASONAL_HEAT), AGREE),
      naturalGas(
        FAC.kent,
        715_000 - KENT_GAS_BILLS[2],
        KENT_GAS_BILLS,
        consumptionDiffers(KENT_GAS_BILLS[2], "therms", "the March bill is missing from the reported total"),
        "kent_gas_mar_2025.pdf"
      ),
      naturalGas(FAC.modesto, 350_000, monthly(350_000, SEASONAL_HEAT), AGREE),
    ],
  },
  {
    id: "s1-stationary-propane",
    box: "scope1",
    category: "Stationary combustion",
    activity: "Propane",
    facilities: [
      deliveredFuel(FAC.tualatin, "Propane", 12_000, PROPANE, factor(T1, 2, 1, "MMBtu per gallon"),
        { issuer: "Columbia Propane", account: "CP-1189", filePrefix: "tualatin_propane" }, ["2025-01-14", "2025-04-02", "2025-10-21", "2025-12-09"]),
      deliveredFuel(FAC.modesto, "Propane", 8_000, PROPANE, factor(T1, 2, 1, "MMBtu per gallon"),
        { issuer: "Valley Propane", account: "VP-6630", filePrefix: "modesto_propane" }, ["2025-02-11", "2025-11-18"]),
    ],
  },
  {
    id: "s1-stationary-diesel",
    box: "scope1",
    category: "Stationary combustion",
    activity: "Diesel",
    facilities: [
      deliveredFuel(FAC.modesto, "Diesel", 5_960, DISTILLATE, factor(T1, 1, 1, "MMBtu per gallon"),
        { issuer: "Valley Fuel Supply", account: "VFS-2207", filePrefix: "modesto_generator_diesel" }, ["2025-03-05", "2025-09-16"]),
    ],
  },
];

/* --- Scope 1 · mobile combustion --- */

const FLEET_CARD = "FleetCard Services";

function fleet(
  fac: Fac,
  activity: string,
  reported: { gal: number; mi: number },
  statements: { gal: number[]; mi: number[] },
  factors: { co2: Factor; ch4: Factor; n2o: Factor },
  cause: string,
  missingFrom?: string
): FacilityResult {
  const total = { gal: statements.gal.reduce((a, b) => a + b, 0), mi: statements.mi.reduce((a, b) => a + b, 0) };
  const spec = { fac, issuer: FLEET_CARD, account: `FC-${fac.code.toUpperCase()}-${activity === "Diesel" ? "D" : "G"}`, filePrefix: `${fac.code}_fleet_${activity.toLowerCase()}` };
  const fuelDocs = monthlyDocs({ ...spec, label: "Gallons", unit: "gal" }, statements.gal, { label: "Miles", values: statements.mi, unit: "mi" });
  const mileDocs = fuelDocs.map((doc) => ({ ...doc, highlight: 3, quantity: Number(doc.lines[3].value.replace(/[^0-9.]/g, "")) }));
  const title = `${fac.name} · ${activity.toLowerCase()} fuel card statements, 2025`;
  const chain = withWorkbookRow(SCOPE1_SHEET, fac, "Mobile combustion", activity, { value: reported.gal, unit: "gal" }, `${formatQuantity(reported.mi)} mi`, (cell) =>
    vehiclesByDistance({
      fuel: {
        reported: { value: reported.gal, unit: "gal", source: cell.quantity },
        recomputed: { value: total.gal, unit: "gal", source: records(title, "gal", fuelDocs, missingFrom) },
      },
      distance: {
        reported: { value: reported.mi, unit: "mi", source: cell.second },
        recomputed: { value: total.mi, unit: "mi", source: records(title, "mi", mileDocs, missingFrom) },
      },
      ...factors,
      gwp: GWP,
    })
  );
  return result(fac, chain, cause);
}

const DIESEL_TRUCKS = { co2: factor(T2, 0, 1, "kg/gal"), ch4: factor(T4, 0, 3, "g/mi"), n2o: factor(T4, 0, 4, "g/mi") };
const GASOLINE_TRUCKS = { co2: factor(T2, 2, 1, "kg/gal"), ch4: factor(T3, 0, 2, "g/mi"), n2o: factor(T3, 0, 3, "g/mi") };
const KENT_DIESEL = { gal: monthly(180_000, FLAT, { 11: 20_000 }), mi: monthly(1_170_000, FLAT, { 11: 130_000 }) };

function forklifts(fac: Fac, gallons: number): FacilityResult {
  const amounts = monthly(gallons, FLAT);
  const docs = monthlyDocs({ fac, issuer: "Columbia Propane", account: "CP-4410", filePrefix: `${fac.code}_forklift_lpg`, label: "Delivered", unit: "gal" }, amounts);
  const chain = withWorkbookRow(SCOPE1_SHEET, fac, "Mobile combustion", "Propane", { value: gallons, unit: "gal" }, "", (cell) =>
    equipmentByFuel({
      fuel: {
        reported: { value: gallons, unit: "gal", source: cell.quantity },
        recomputed: { value: gallons, unit: "gal", source: records(`${fac.name} · forklift propane deliveries, 2025`, "gal", docs) },
      },
      how: "Sum of monthly deliveries (forklifts)",
      co2: factor(T2, 1, 1, "kg/gal"),
      ch4: factor(T5, 0, 2, "g/gal"),
      n2o: factor(T5, 0, 3, "g/gal"),
      gwp: GWP,
    })
  );
  return result(fac, chain, AGREE);
}

const mobile: ResultLine[] = [
  {
    id: "s1-mobile-diesel",
    box: "scope1",
    category: "Mobile combustion",
    activity: "Diesel",
    facilities: [
      fleet(FAC.tualatin, "Diesel", { gal: 180_000, mi: 1_170_000 }, { gal: monthly(180_000, FLAT), mi: monthly(1_170_000, FLAT) }, DIESEL_TRUCKS, AGREE),
      fleet(
        FAC.kent,
        "Diesel",
        { gal: 180_000 - KENT_DIESEL.gal[11], mi: 1_170_000 - KENT_DIESEL.mi[11] },
        KENT_DIESEL,
        DIESEL_TRUCKS,
        `Fuel differs by ${formatQuantity(KENT_DIESEL.gal[11])} gal and distance by ${formatQuantity(KENT_DIESEL.mi[11])} mi: ` +
          "the December fuel card statement is missing from the reported total. Factors and GWPs match.",
        "kent_fleet_diesel_dec_2025.pdf"
      ),
      fleet(FAC.modesto, "Diesel", { gal: 108_900, mi: 707_850 }, { gal: monthly(108_900, FLAT), mi: monthly(707_850, FLAT) }, DIESEL_TRUCKS, AGREE),
    ],
  },
  {
    id: "s1-mobile-gasoline",
    box: "scope1",
    category: "Mobile combustion",
    activity: "Gasoline",
    facilities: [
      fleet(FAC.tualatin, "Gasoline", { gal: 30_000, mi: 600_000 }, { gal: monthly(30_000, FLAT), mi: monthly(600_000, FLAT) }, GASOLINE_TRUCKS, AGREE),
      fleet(FAC.kent, "Gasoline", { gal: 30_500, mi: 610_000 }, { gal: monthly(30_500, FLAT), mi: monthly(610_000, FLAT) }, GASOLINE_TRUCKS, AGREE),
    ],
  },
  { id: "s1-mobile-propane", box: "scope1", category: "Mobile combustion", activity: "Propane", facilities: [forklifts(FAC.kent, 39_000)] },
];

/* --- Scope 1 · fugitive emissions --- */

function refrigerant(
  fac: Fac,
  gas: string,
  gwp: Factor,
  services: { date: string; amount: number }[],
  reported: number,
  cause: string,
  missingFrom?: string
): FacilityResult {
  const recomputed = services.reduce((sum, s) => sum + s.amount, 0);
  const docs = datedDocs({ fac, issuer: "Northwest Cold Service", account: `NCS-${fac.code.toUpperCase()}`, filePrefix: `${fac.code}_refrigerant_service`, label: `${gas} added`, unit: "kg" }, services);
  const chain = withWorkbookRow(SCOPE1_SHEET, fac, "Fugitive emissions", gas, { value: reported, unit: "kg" }, "", (cell) =>
    refrigerantByMass({
      added: {
        reported: { value: reported, unit: "kg", source: cell.quantity },
        recomputed: { value: recomputed, unit: "kg", source: records(`${fac.name} · ${gas} service records, 2025`, "kg", docs, missingFrom) },
      },
      gwp,
    })
  );
  return result(fac, chain, cause);
}

const TUALATIN_404A = [
  { date: "2025-02-12", amount: 120 },
  { date: "2025-05-20", amount: 100 },
  { date: "2025-08-07", amount: 160 },
  { date: "2025-11-14", amount: 40 },
];

const fugitive: ResultLine[] = [
  {
    id: "s1-fugitive-r404a",
    box: "scope1",
    category: "Fugitive emissions",
    activity: "R-404A",
    facilities: [
      refrigerant(
        FAC.tualatin, "R-404A", factor(T12, 0, 1, ""), TUALATIN_404A, 380,
        "Refrigerant added differs by 40 kg: the November service record is missing from the reported total. The GWP matches.",
        "tualatin_refrigerant_service_2025-11-14.pdf"
      ),
      refrigerant(FAC.kent, "R-404A", factor(T12, 0, 1, ""), [{ date: "2025-03-18", amount: 90 }, { date: "2025-07-22", amount: 130 }], 220, AGREE),
    ],
  },
  {
    id: "s1-fugitive-r410a",
    box: "scope1",
    category: "Fugitive emissions",
    activity: "R-410A",
    facilities: [refrigerant(FAC.modesto, "R-410A", factor(T12, 1, 1, ""), [{ date: "2025-04-09", amount: 15 }, { date: "2025-09-23", amount: 25 }], 40, AGREE)],
  },
  {
    id: "s1-fugitive-hfc134a",
    box: "scope1",
    category: "Fugitive emissions",
    activity: "HFC-134a",
    facilities: [refrigerant(FAC.kent, "HFC-134a", factor(T11, 3, 1, ""), [{ date: "2025-06-11", amount: 24.6 }], 24.6, AGREE)],
  },
];

/* --- Scope 2 --- */

const POWER_DOCS: Record<Fac["code"], Omit<DocSpec, "label" | "unit">> = {
  tualatin: { fac: FAC.tualatin, issuer: "Tualatin Valley Power", account: "TVP-88213", filePrefix: "tualatin_electric" },
  kent: { fac: FAC.kent, issuer: "Green River Power", account: "GRP-40977", filePrefix: "kent_electric" },
  modesto: { fac: FAC.modesto, issuer: "Stanislaus Gas & Power", account: "SGP-5521-10", filePrefix: "modesto_electric" },
};
const SUBREGION: Record<Fac["code"], keyof typeof GRID> = { tualatin: "NWPP", kent: "NWPP", modesto: "CAMX" };
const ANNUAL_MWH: Record<Fac["code"], number> = { tualatin: 9_000, kent: 7_200, modesto: 6_095 };

function powerRecords(fac: Fac): RecordsSource {
  const docs = monthlyDocs({ ...POWER_DOCS[fac.code], label: "Energy used", unit: "MWh" }, monthly(ANNUAL_MWH[fac.code], SEASONAL_POWER));
  return records(`${fac.name} · electricity bills, 2025`, "MWh", docs);
}

function electricityLocation(fac: Fac): FacilityResult {
  const mwh = ANNUAL_MWH[fac.code];
  const chain = withWorkbookRow(SCOPE2_SHEET, fac, "Scope 2 location-based", "Electricity", { value: mwh, unit: "MWh" }, SUBREGION[fac.code], (cell) =>
    electricityByGrid({
      consumption: { reported: { value: mwh, unit: "MWh", source: cell.quantity }, recomputed: { value: mwh, unit: "MWh", source: powerRecords(fac) } },
      ...GRID[SUBREGION[fac.code]],
      gwp: GWP,
    })
  );
  return result(fac, chain, AGREE);
}

const PPA: DocumentSource = {
  kind: "document", filename: "cascade_ppa_greenpower.pdf", page: 3, issuer: "Columbia Wind Partners", period: "2025",
  facility: FAC.tualatin.name,
  lines: [
    { label: "Contract", value: "Green power purchase agreement CWP-2023-07" },
    { label: "Delivery point", value: "Tualatin Plant" },
    { label: "Certificates retired for 2025", value: "8,000 MWh" },
    { label: "Retirement registry", value: "WREGIS · retired 2026-01-30" },
  ],
  highlight: 2, quantity: 8_000,
};

function noContract(fac: Fac): BasisSource {
  return {
    kind: "basis",
    title: `${fac.name} · contractual instruments`,
    text: "No supply contract, green tariff or certificate retirement covers this facility in 2025, so all of its electricity takes the grid factor (no residual mix is published for its region).",
  };
}

function electricityMarket(fac: Fac, covered: { reported: number; recomputed: number }, cause: string): FacilityResult {
  const mwh = ANNUAL_MWH[fac.code];
  const chain = withWorkbookRow(SCOPE2_SHEET, fac, "Scope 2 market-based", "Electricity", { value: mwh, unit: "MWh" }, `${formatQuantity(covered.reported)} MWh covered`, (cell) =>
    electricityByContract({
      consumption: { reported: { value: mwh, unit: "MWh", source: cell.quantity }, recomputed: { value: mwh, unit: "MWh", source: powerRecords(fac) } },
      covered: {
        reported: { value: covered.reported, unit: "MWh", source: cell.second },
        recomputed: { value: covered.recomputed, unit: "MWh", source: covered.recomputed ? PPA : noContract(fac) },
      },
      ...GRID[SUBREGION[fac.code]],
      gwp: GWP,
    })
  );
  return result(fac, chain, cause);
}

function thermal(
  sheetCategory: string,
  activity: "Steam" | "Heating",
  fac: Fac,
  mmbtu: number,
  doc: Omit<DocSpec, "label" | "unit" | "fac">,
  clientCo2?: number
): FacilityResult {
  const docs = monthlyDocs({ ...doc, fac, label: "Energy delivered", unit: "MMBtu" }, monthly(mmbtu, SEASONAL_HEAT));
  const second = clientCo2 ? `${clientCo2.toFixed(2)} kg CO₂/MMBtu` : "";
  const chain = withWorkbookRow(SCOPE2_SHEET, fac, sheetCategory, activity, { value: mmbtu, unit: "MMBtu" }, second, (cell) =>
    thermalByEnergy({
      energy: {
        reported: { value: mmbtu, unit: "MMBtu", source: cell.quantity },
        recomputed: { value: mmbtu, unit: "MMBtu", source: records(`${fac.name} · ${activity.toLowerCase()} statements, 2025`, "MMBtu", docs) },
      },
      ...STEAM_HEAT,
      co2: clientCo2
        ? { reported: { value: clientCo2, text: clientCo2.toFixed(2), unit: "kg/MMBtu", source: cell.second }, recomputed: STEAM_HEAT.co2 }
        : STEAM_HEAT.co2,
      gwp: GWP,
    })
  );
  const cause = clientCo2
    ? `The client applied ${clientCo2.toFixed(2)} kg CO₂/MMBtu from the supplier's 2023 statement; no 2025 supplier factor is ` +
      `on file, so the EPA default of ${STEAM_HEAT.co2.text} kg/MMBtu applies. Energy delivered matches.`
    : AGREE;
  return result(fac, chain, cause);
}

const STEAM_DOC = { issuer: "Kent District Energy", account: "KDE-2210", filePrefix: "kent_steam" };
const HEAT_DOC = { issuer: "Tualatin District Heat", account: "TDH-0912", filePrefix: "tualatin_district_heat" };
const HEATING_CLIENT_CO2 = 61.2;

const scope2: ResultLine[] = [
  { id: "s2l-electricity", box: "scope2_location", activity: "Electricity", facilities: [electricityLocation(FAC.tualatin), electricityLocation(FAC.kent), electricityLocation(FAC.modesto)] },
  { id: "s2l-steam", box: "scope2_location", activity: "Steam", facilities: [thermal("Scope 2 location-based", "Steam", FAC.kent, 3_163, STEAM_DOC)] },
  { id: "s2l-heating", box: "scope2_location", activity: "Heating", facilities: [thermal("Scope 2 location-based", "Heating", FAC.tualatin, 1_385, HEAT_DOC, HEATING_CLIENT_CO2)] },
  {
    id: "s2m-electricity",
    box: "scope2_market",
    activity: "Electricity",
    facilities: [
      electricityMarket(
        FAC.tualatin,
        { reported: 9_000, recomputed: 8_000 },
        "Contract coverage differs by 1,000 MWh: the PPA retirement statement covers 8,000 MWh, the client applied 9,000 MWh. Factors match."
      ),
      electricityMarket(FAC.kent, { reported: 0, recomputed: 0 }, AGREE),
      electricityMarket(FAC.modesto, { reported: 0, recomputed: 0 }, AGREE),
    ],
  },
  { id: "s2m-steam", box: "scope2_market", activity: "Steam", facilities: [thermal("Scope 2 market-based", "Steam", FAC.kent, 3_163, STEAM_DOC)] },
  { id: "s2m-heating", box: "scope2_market", activity: "Heating", facilities: [thermal("Scope 2 market-based", "Heating", FAC.tualatin, 1_385, HEAT_DOC, HEATING_CLIENT_CO2)] },
];

/* --- Biogenic CO2 --- */

function wood(fac: Fac, tickets: { date: string; amount: number }[]): FacilityResult {
  const tons = Math.round(tickets.reduce((sum, t) => sum + t.amount, 0) * 10) / 10;
  const docs = datedDocs({ fac, issuer: "Cascade Wood Products", account: `CWP-${fac.code.toUpperCase()}`, filePrefix: `${fac.code}_wood_ticket`, label: "Delivered", unit: "short tons" }, tickets);
  const chain = withWorkbookRow(BIOGENIC_SHEET, fac, "Biogenic CO₂", "Wood and wood residuals", { value: tons, unit: "short tons" }, "", (cell) =>
    biogenicByEnergy({
      consumption: {
        reported: { value: tons, unit: "short tons", source: cell.quantity },
        recomputed: { value: tons, unit: "short tons", source: records(`${fac.name} · wood delivery tickets, 2025`, "short tons", docs) },
      },
      heatContent: factor(T1, 3, 1, "MMBtu per short ton"),
      co2: factor(T1, 3, 2, "kg/MMBtu"),
    })
  );
  return result(fac, chain, AGREE);
}

const biogenic: ResultLine[] = [
  {
    id: "bio-direct",
    box: "biogenic",
    activity: "Direct",
    facilities: [
      wood(FAC.tualatin, [{ date: "2025-01-20", amount: 20 }, { date: "2025-06-03", amount: 15 }, { date: "2025-10-28", amount: 15 }]),
      wood(FAC.kent, [{ date: "2025-02-17", amount: 12 }, { date: "2025-07-08", amount: 11.4 }, { date: "2025-11-25", amount: 12 }]),
    ],
  },
];

/** The demo's inventory lines, every box; Process emissions and Cooling are not reported. */
export const verificationLines: ResultLine[] = [...stationary, ...mobile, ...fugitive, ...scope2, ...biogenic];

/** One examination already recorded, so the Examined column starts with something in it. */
export const seedExaminations: Record<string, Examination> = {
  [examinationKey("s1-stationary-natural-gas", FAC.tualatin.id)]: {
    examinationState: "examined_no_exceptions",
    nextActionWith: "none",
    examinedBy: "R. Iqbal",
    examinedByLogin: "riqbal",
    examinedAt: "2026-02-03T15:20:00.000Z",
    note: "Agreed the twelve monthly bills to the workbook.",
  },
};

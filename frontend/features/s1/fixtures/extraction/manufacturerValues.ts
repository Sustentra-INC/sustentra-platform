import type { ReviewValue, ScopePlacement, SourceKind, ValueRecordEntry } from "../../types/review";

/**
 * Extracted values for Cascade Provisions, keyed to the workspace documents.
 * Enough breadth to exercise the navigator (facility -> type, entity-level
 * workbook sections, not-yet-known), plus:
 *   - Scope 2 always as two values (location-based + market-based)
 *   - a corrected value that keeps the machine original visible
 *   - a requested value
 *   - a value the extractor could not find (Missing data pre-fill)
 *   - values with a span (overlay renderer) and values without (fallback)
 *   - the two stressor walls (312 mileage rows, 218 supplier rows)
 */

const FAC = { tualatin: "facility-tualatin", kent: "facility-kent", modesto: "facility-modesto" } as const;
const FAC_NAME: Record<string, string> = {
  "facility-tualatin": "Tualatin Plant",
  "facility-kent": "Kent Cannery",
  "facility-modesto": "Modesto Bottling",
};

let n = 0;
const machine = (value: string, from = "from page"): ValueRecordEntry[] => [
  { kind: "machine", actor: "System", at: "2025-09-10T08:00:00Z", action: "read", reason: `${value} · ${from}` },
];

/** Placeholder methodology field id, stable per (what-it-is + scope). */
function mfPlaceholder(whatItIs: string, scope: ScopePlacement): string {
  const slug = whatItIs.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const scopeTag = scope.startsWith("scope2") ? `-${scope}` : "";
  return `MF-PLH-${slug}${scopeTag}`;
}

function rv(p: Partial<ReviewValue> & { documentId: string; filename: string; documentType: string; whatItIs: string; scope: ScopePlacement; value: string; unit: string }): ReviewValue {
  n += 1;
  return {
    id: p.id ?? `V-${String(n).padStart(4, "0")}`,
    methodologyFieldId: p.methodologyFieldId ?? mfPlaceholder(p.whatItIs, p.scope),
    facilityId: p.facilityId ?? null,
    period: p.period ?? "2025",
    reviewState: p.reviewState ?? "to_review",
    record: p.record ?? machine(`${p.value} ${p.unit}`),
    sourceKind: (p.sourceKind ?? "pdf") as SourceKind,
    page: p.page ?? 1,
    pageCount: p.pageCount ?? 2,
    span: p.span ?? null,
    snippet: p.snippet ?? null,
    ...p,
  };
}

const values: ReviewValue[] = [];
const slug = (fid: string) => FAC_NAME[fid].split(" ")[0].toLowerCase();

// electricity — Scope 2 always two values (location + market), with a span.
function electricity(fid: string, month: string, kwh: number) {
  const file = `${slug(fid)}_electric_${month.toLowerCase()}_2025.pdf`;
  const period = `${month} 2025`;
  const span = { page: 1, x: 0.58, y: 0.42, w: 0.3, h: 0.05 };
  values.push(
    rv({
      documentId: `DOC-${slug(fid)}-elec-${month.toLowerCase()}`,
      filename: file,
      documentType: "Electricity bill",
      facilityId: fid,
      period,
      whatItIs: "Electricity consumed",
      scope: "scope2_location",
      value: kwh.toLocaleString(),
      unit: "kWh",
      sourceKind: "pdf",
      span,
      requestPreselect: "clarify",
    }),
    rv({
      documentId: `DOC-${slug(fid)}-elec-${month.toLowerCase()}`,
      filename: file,
      documentType: "Electricity bill",
      facilityId: fid,
      period,
      whatItIs: "Electricity consumed",
      scope: "scope2_market",
      value: kwh.toLocaleString(),
      unit: "kWh",
      sourceKind: "pdf",
      span,
      requestPreselect: "clarify",
    })
  );
}

// natural gas — Scope 1, with a span.
function gas(fid: string, month: string, therms: number, extra?: Partial<ReviewValue>) {
  const file = `${slug(fid)}_gas_${month.toLowerCase()}_2025.pdf`;
  values.push(
    rv({
      documentId: `DOC-${slug(fid)}-gas-${month.toLowerCase()}`,
      filename: file,
      documentType: "Natural gas bill",
      facilityId: fid,
      period: `${month} 2025`,
      whatItIs: "Natural gas consumed",
      scope: "scope1",
      value: therms.toLocaleString(),
      unit: "therms",
      sourceKind: "pdf",
      span: { page: 1, x: 0.6, y: 0.5, w: 0.28, h: 0.05 },
      requestPreselect: "clarify",
      ...extra,
    })
  );
}

([FAC.tualatin, FAC.kent, FAC.modesto] as string[]).forEach((fid, i) => {
  electricity(fid, "Jan", 410000 + i * 90000);
  electricity(fid, "Apr", 428000 + i * 90000);
  gas(fid, "Jan", 28000 + i * 7000);
  gas(fid, "Apr", 29200 + i * 7000);
  // refrigerant — Scope 1, no span (fallback state).
  values.push(
    rv({
      documentId: `DOC-${slug(fid)}-refrig`,
      filename: `${slug(fid)}_refrigerant_service.pdf`,
      documentType: "Refrigerant service log or refrigerant purchase invoice",
      facilityId: fid,
      period: "2025",
      whatItIs: "R-404A added on service",
      scope: "scope1",
      value: `${12 + i * 3}`,
      unit: "kg",
      sourceKind: "pdf",
      span: null,
      snippet: "Charge added: R-404A 12 kg — unit RTU-3",
      requestPreselect: "clarify",
    })
  );
  // meter — Scope 2 location, image, no span.
  values.push(
    rv({
      documentId: `DOC-${slug(fid)}-meter`,
      filename: `${slug(fid)}_meter_dec.jpg`,
      documentType: "Meter reading or meter photo",
      facilityId: fid,
      period: "Dec 2025",
      whatItIs: "Electricity meter read",
      scope: "scope2_location",
      value: (512340 + i * 1000).toLocaleString(),
      unit: "kWh",
      sourceKind: "image",
      span: null,
      snippet: "Photo of dial meter — read entered by verifier",
    })
  );
});

// a withdrawn document open in review — cards grey, actions disabled, reason.
values.push(
  rv({
    documentId: "DOC-tualatin-elec-jul-dupe",
    filename: "tualatin_electric_july_copy.pdf",
    documentType: "Electricity bill",
    facilityId: FAC.tualatin,
    period: "Jul 2025",
    whatItIs: "Electricity consumed",
    scope: "scope2_location",
    value: "418,200",
    unit: "kWh",
    withdrawn: true,
    withdrawnReason: "Document withdrawn — duplicate of the July electricity bill.",
    span: { page: 1, x: 0.58, y: 0.42, w: 0.3, h: 0.05 },
  })
);

// one corrected value (machine original stays visible) — Tualatin April gas.
gas(FAC.tualatin, "AprCorr", 34200, {
  documentId: "DOC-tualatin-gas-aprcorr",
  filename: "tualatin_gas_apr_2025_corrected.pdf",
  period: "Apr 2025",
  reviewState: "corrected",
  originalValue: "3,420",
  record: [
    { kind: "machine", actor: "System", at: "2025-09-10T08:00:00Z", action: "read", reason: "3,420 therms · from page" },
    { kind: "human", actor: "M. Osei", at: "2025-09-15T10:24:00Z", action: "corrected value", reason: "OCR dropped a digit — 34,200 on the page" },
  ],
});

// one accepted value — Kent January electricity location-based.
values.push(
  rv({
    documentId: "DOC-kent-elec-jan",
    filename: "kent_electric_jan_2025.pdf",
    documentType: "Electricity bill",
    facilityId: FAC.kent,
    period: "Jan 2025",
    whatItIs: "Peak demand",
    scope: "not_placed",
    value: "1,240",
    unit: "kW",
    reviewState: "accepted",
    record: [
      { kind: "machine", actor: "System", at: "2025-09-10T08:00:00Z", action: "read", reason: "1,240 kW · from page" },
      { kind: "human", actor: "M. Osei", at: "2025-09-15T10:05:00Z", action: "accepted as read" },
    ],
    span: { page: 1, x: 0.6, y: 0.62, w: 0.2, h: 0.04 },
  })
);

// one requested value — Modesto refrigerant recovered (illegible).
values.push(
  rv({
    documentId: "DOC-modesto-refrig",
    filename: "modesto_refrigerant_service.pdf",
    documentType: "Refrigerant service log or refrigerant purchase invoice",
    facilityId: FAC.modesto,
    period: "2025",
    whatItIs: "R-404A recovered on service",
    scope: "scope1",
    value: "—",
    unit: "kg",
    reviewState: "requested",
    requestPreselect: "clarify",
    record: [
      { kind: "machine", actor: "System", at: "2025-09-10T08:00:00Z", action: "read", reason: "no value · illegible" },
      { kind: "human", actor: "M. Osei", at: "2025-09-15T09:58:00Z", action: "requested from client", reason: "service log illegible — asked for the invoice" },
    ],
    span: null,
    snippet: "Recovered to cylinder: (illegible)",
  })
);

// a value the extractor could not find (Missing data pre-fill).
values.push(
  rv({
    documentId: "DOC-PARTIAL",
    filename: "kent_gas_sep_2025.pdf",
    documentType: "Natural gas bill",
    facilityId: FAC.kent,
    period: "Sep 2025",
    whatItIs: "Service period end date",
    scope: "not_placed",
    value: "not found",
    unit: "",
    requestPreselect: "missing_data",
    span: null,
    snippet: "Service period: 2025-09-01 to (not printed)",
  })
);

// entity-level: inventory workbook, children are its sections.
const wbSpread = (cell: string) => ({ sourceKind: "spreadsheet" as SourceKind, sheet: "Inventory", cell, span: null });
values.push(
  rv({ documentId: "DOC-WORKBOOK", filename: "cascade_inventory_workbook_2025.xlsx", documentType: "Inventory workbook", entityLevel: true, section: "general", period: "FY2025", whatItIs: "Organizational boundary approach", scope: "general", value: "Operational control", unit: "", ...wbSpread("B3") }),
  rv({ documentId: "DOC-WORKBOOK", filename: "cascade_inventory_workbook_2025.xlsx", documentType: "Inventory workbook", entityLevel: true, section: "scope1", period: "FY2025", whatItIs: "Total Scope 1 (client calc)", scope: "scope1", value: "18,240", unit: "tCO₂e", ...wbSpread("D12") }),
  rv({ documentId: "DOC-WORKBOOK", filename: "cascade_inventory_workbook_2025.xlsx", documentType: "Inventory workbook", entityLevel: true, section: "scope1", period: "FY2025", whatItIs: "Stationary combustion subtotal", scope: "scope1", value: "12,110", unit: "tCO₂e", ...wbSpread("D14") }),
  rv({ documentId: "DOC-WORKBOOK", filename: "cascade_inventory_workbook_2025.xlsx", documentType: "Inventory workbook", entityLevel: true, section: "scope2", period: "FY2025", whatItIs: "Total Scope 2, location-based (client calc)", scope: "scope2_location", value: "9,880", unit: "tCO₂e", ...wbSpread("D20") }),
  rv({ documentId: "DOC-WORKBOOK", filename: "cascade_inventory_workbook_2025.xlsx", documentType: "Inventory workbook", entityLevel: true, section: "scope2", period: "FY2025", whatItIs: "Total Scope 2, market-based (client calc)", scope: "scope2_market", value: "7,410", unit: "tCO₂e", ...wbSpread("D21") })
);

// entity-level: boundary statement (text) and factor list.
values.push(
  rv({ documentId: "DOC-BOUNDARY", filename: "cascade_org_boundary_statement.pdf", documentType: "Organizational boundary statement", entityLevel: true, period: "FY2025", whatItIs: "Consolidation approach stated", scope: "general", value: "Operational control", unit: "", sourceKind: "text", span: null, snippet: "“The company consolidates on an operational-control basis for the 2025 reporting year.”" }),
  rv({ documentId: "DOC-FACTORS", filename: "cascade_emission_factors_2025.pdf", documentType: "Emission factor source list", entityLevel: true, period: "FY2025", whatItIs: "Grid emission factor cited (WECC)", scope: "not_placed", value: "0.223", unit: "kgCO₂e/kWh", sourceKind: "pdf", span: { page: 1, x: 0.5, y: 0.3, w: 0.24, h: 0.04 } })
);

// not-yet-known: a value read from an unclassified file.
values.push(
  rv({ documentId: "DOC-UNCLASS-1", filename: "IMG_2231.jpg", documentType: "Type unresolved", notYetKnown: true, period: "unknown", whatItIs: "Number read from an unclassified image", scope: "not_placed", value: "1,204", unit: "(unit unread)", sourceKind: "image", span: null, snippet: "1,204 — type not set" })
);

// ---- stressor 1: mileage report, 312 rows from one file (Scope 1) ----
for (let i = 1; i <= 312; i += 1) {
  values.push(
    rv({
      documentId: "DOC-MILEAGE",
      filename: "mileage_reimbursement_2025.xlsx",
      documentType: "Mileage or expense report",
      facilityId: FAC.tualatin,
      period: "2025",
      whatItIs: `Trip ${String(i).padStart(3, "0")} — mileage claimed`,
      scope: "scope1",
      value: `${18 + ((i * 7) % 140)}`,
      unit: "mi",
      sourceKind: "spreadsheet",
      sheet: "Mileage",
      cell: `C${i + 1}`,
      span: null,
    })
  );
}

// ---- stressor 2: supplier roster, 218 entries (not placed) ----
for (let i = 1; i <= 218; i += 1) {
  values.push(
    rv({
      documentId: "DOC-ROSTER",
      filename: "supplier_roster_FY2025.csv",
      documentType: "Supplier roster",
      entityLevel: true,
      period: "FY2025",
      whatItIs: `Supplier ${String(i).padStart(3, "0")} — annual spend`,
      scope: "not_placed",
      value: `$${((12 + ((i * 13) % 900)) * 1000).toLocaleString()}`,
      unit: "",
      sourceKind: "spreadsheet",
      sheet: "Suppliers",
      cell: `E${i + 1}`,
      span: null,
    })
  );
}

export const manufacturerValues: ReviewValue[] = values;
export const FACILITY_NAMES = FAC_NAME;

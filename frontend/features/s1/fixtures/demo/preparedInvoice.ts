import type { EvidenceItem } from "../../types/evidence";
import type { ReviewValue } from "../../types/review";
import { INVOICE_MARKS } from "../../components/demo/InvoicePage";

/**
 * The one prepared document for the demo: an electricity invoice for Cascade
 * Provisions (Kent Cannery, Feb 2025). Its extracted values carry spans authored
 * onto the InvoicePage render, so the highlight lands exactly on the figure.
 */

export const DEMO_INVOICE_ID = "DOC-DEMO-INVOICE";
export const DEMO_INVOICE_FILENAME = "kent_electricity_feb_2025.pdf";

const reviewer = { id: "client-cascade", name: "Cascade Provisions", actorType: "preparer" as const };

export function preparedInvoiceEvidence(now: string): EvidenceItem {
  return {
    documentId: DEMO_INVOICE_ID,
    filename: DEMO_INVOICE_FILENAME,
    downloadUrl: `#/${DEMO_INVOICE_ID}`,
    format: "pdf",
    uploadedBy: { id: "local_reviewer", name: "You", actorType: "reviewer" },
    uploadedAt: now,
    evidenceClass: "main",
    disposition: "active",
    processingState: "not_ingested",
    haltReason: null,
    detectedType: null,
    typeReviewBand: null,
    typeReviewReason: null,
    facilityState: "unresolved",
    facilityId: null,
    facilityName: null,
    facilityCount: null,
    periodState: "unresolved",
    periodStart: null,
    periodEnd: null,
    fieldsExpected: 6,
    fieldsExpectedDisplay: 6,
    fieldsExtracted: 0,
    documentProperties: [],
    relationships: [],
    reviewArea: null,
    note: null,
    notes: [],
    answeredRequestNumber: null,
    arrivedSinceLastVisit: true,
    missingFields: [],
  };
}

/** What the classifier "resolves" the invoice to, once analysis finishes. */
export const preparedInvoiceClassified: Partial<EvidenceItem> = {
  processingState: "extracted",
  detectedType: "Electricity bill",
  facilityState: "resolved",
  facilityId: "facility-kent",
  facilityName: "Kent Cannery",
  periodState: "resolved",
  periodStart: "2025-02-01",
  periodEnd: "2025-02-28",
  fieldsExtracted: 6,
};

const span = (mark: { x: number; y: number; w: number; h: number }) => ({ page: 1, ...mark });

function machine(value: string): ReviewValue["record"] {
  return [{ kind: "machine", actor: "System", at: "2025-03-08T09:00:00Z", action: "read", reason: `${value} · from the invoice` }];
}

const base = {
  documentId: DEMO_INVOICE_ID,
  filename: DEMO_INVOICE_FILENAME,
  documentType: "Electricity bill",
  facilityId: "facility-kent",
  period: "Feb 2025",
  reviewState: "to_review" as const,
  sourceKind: "pdf" as const,
  page: 1,
  pageCount: 1,
};

/**
 * The extracted values, each mapped to a highlighted figure on the invoice, in
 * the order the scripted beat reveals them. A compliance analyst reads more than
 * the kWh: the period, both Scope-2 bases, peak demand, the emission factor and
 * the derived emissions all get their own card and their own highlight.
 */
export const preparedInvoiceValues: ReviewValue[] = [
  {
    ...base,
    id: "DV-elec-loc",
    whatItIs: "Electricity consumed",
    scope: "scope2_location",
    value: "182,400",
    unit: "kWh",
    methodologyFieldId: "MF-PLH-electricity-consumed-scope2_location",
    record: machine("182,400 kWh"),
    span: span(INVOICE_MARKS.consumption),
    requestPreselect: "clarify",
  },
  {
    ...base,
    id: "DV-elec-mkt",
    whatItIs: "Electricity consumed",
    scope: "scope2_market",
    value: "182,400",
    unit: "kWh",
    methodologyFieldId: "MF-PLH-electricity-consumed-scope2_market",
    record: machine("182,400 kWh"),
    span: span(INVOICE_MARKS.consumption),
    requestPreselect: "clarify",
  },
  {
    ...base,
    id: "DV-demand",
    whatItIs: "Peak demand",
    scope: "not_placed",
    value: "1,240",
    unit: "kW",
    record: machine("1,240 kW"),
    span: span(INVOICE_MARKS.demand),
  },
  {
    ...base,
    id: "DV-period",
    whatItIs: "Billing period",
    scope: "general",
    value: "01 Feb – 28 Feb 2025",
    unit: "",
    record: machine("01 Feb – 28 Feb 2025"),
    span: span(INVOICE_MARKS.period),
  },
  {
    ...base,
    id: "DV-factor",
    whatItIs: "Emission factor (location-based)",
    scope: "scope2_location",
    value: "0.223",
    unit: "kgCO2e/kWh",
    record: machine("0.223 kgCO2e/kWh"),
    span: span(INVOICE_MARKS.emissionFactor),
    requestPreselect: "confirm_or_restate",
  },
  {
    ...base,
    id: "DV-emissions",
    whatItIs: "Location-based emissions",
    scope: "scope2_location",
    value: "40.68",
    unit: "tCO2e",
    record: machine("40.68 tCO2e"),
    span: span(INVOICE_MARKS.emissions),
  },
];

/** Short labels for the scripted "values appearing" ticker. */
export const preparedInvoiceFoundOrder = [
  "Electricity consumed · 182,400 kWh",
  "Peak demand · 1,240 kW",
  "Emission factor · 0.223 kgCO2e/kWh",
  "Location-based emissions · 40.68 tCO2e",
];

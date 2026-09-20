import type { EvidenceItem } from "../../types/evidence";
import type { ReviewValue } from "../../types/review";
import { INVOICE_HIGHLIGHT } from "../../components/demo/InvoicePage";

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
    fieldsExpected: 3,
    fieldsExpectedDisplay: 3,
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
  fieldsExtracted: 3,
};

const span = (extra?: Partial<{ x: number; y: number; w: number; h: number }>) => ({
  page: 1,
  ...INVOICE_HIGHLIGHT,
  ...extra,
});

function machine(value: string): ReviewValue["record"] {
  return [{ kind: "machine", actor: "System", at: "2025-03-08T09:00:00Z", action: "read", reason: `${value} · from the invoice` }];
}

/** The "found" values, in the order the scripted beat reveals them. */
export const preparedInvoiceValues: ReviewValue[] = [
  {
    id: "DV-elec-loc",
    documentId: DEMO_INVOICE_ID,
    filename: DEMO_INVOICE_FILENAME,
    documentType: "Electricity bill",
    facilityId: "facility-kent",
    period: "Feb 2025",
    whatItIs: "Electricity consumed",
    scope: "scope2_location",
    value: "182,400",
    unit: "kWh",
    methodologyFieldId: "MF-PLH-electricity-consumed-scope2_location",
    reviewState: "to_review",
    record: machine("182,400 kWh"),
    sourceKind: "pdf",
    page: 1,
    pageCount: 1,
    span: span(),
    requestPreselect: "clarify",
  },
  {
    id: "DV-elec-mkt",
    documentId: DEMO_INVOICE_ID,
    filename: DEMO_INVOICE_FILENAME,
    documentType: "Electricity bill",
    facilityId: "facility-kent",
    period: "Feb 2025",
    whatItIs: "Electricity consumed",
    scope: "scope2_market",
    value: "182,400",
    unit: "kWh",
    methodologyFieldId: "MF-PLH-electricity-consumed-scope2_market",
    reviewState: "to_review",
    record: machine("182,400 kWh"),
    sourceKind: "pdf",
    page: 1,
    pageCount: 1,
    span: span(),
    requestPreselect: "clarify",
  },
  {
    id: "DV-demand",
    documentId: DEMO_INVOICE_ID,
    filename: DEMO_INVOICE_FILENAME,
    documentType: "Electricity bill",
    facilityId: "facility-kent",
    period: "Feb 2025",
    whatItIs: "Peak demand",
    scope: "not_placed",
    value: "1,240",
    unit: "kW",
    reviewState: "to_review",
    record: machine("1,240 kW"),
    sourceKind: "pdf",
    page: 1,
    pageCount: 1,
    span: span({ y: 0.455, h: 0.024 }),
  },
];

/** Short labels for the scripted "values appearing" ticker. */
export const preparedInvoiceFoundOrder = [
  "Electricity consumed — 182,400 kWh",
  "Peak demand — 1,240 kW",
  "Billing period — Feb 2025",
];

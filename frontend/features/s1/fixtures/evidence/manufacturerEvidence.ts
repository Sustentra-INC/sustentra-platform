import type { Actor } from "../../types/engagement";
import type { EvidenceItem, EvidenceFormat } from "../../types/evidence";

/**
 * Fixture evidence for Cascade Provisions Co. · a three-facility food
 * manufacturer, 2025 reporting year, ~150 files across the canonical type
 * vocabulary, built to carry the mess the interface must survive:
 *   - two duplicate electricity bills
 *   - a prior-year inventory and a wrong-year bill (period outside 2025)
 *   - one unreadable scan (blocked)
 *   - two unclassifiable files (type unresolved)
 *   - one workbook covering all three facilities
 *   - Tualatin missing two months of electricity (Feb, Mar absent)
 *   - one partially extracted gas bill, one conflicting pair, one supersede
 * plus the two stressor documents that break one-card-per-value:
 *   - a mileage/expense report yielding 312 rows from one file
 *   - a supplier roster with 218 entries
 *
 * These stressors are ONE workspace row each; the row-per-value failure shows
 * on Extraction Review, so each carries a large fieldsExpected count here.
 */

const preparer: Actor = { id: "client-cascade", name: "Cascade Provisions", actorType: "preparer" };

const FAC = {
  tualatin: { facilityId: "facility-tualatin", name: "Tualatin Plant" },
  kent: { facilityId: "facility-kent", name: "Kent Cannery" },
  modesto: { facilityId: "facility-modesto", name: "Modesto Bottling" },
} as const;

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];
const MONTH_DAYS = ["31", "28", "31", "30", "31", "30", "31", "31", "30", "31", "30", "31"];

let seq = 0;
function nextId(): string {
  seq += 1;
  return `DOC-${String(seq).padStart(4, "0")}`;
}

function base(over: Partial<EvidenceItem> & { filename: string; detectedType: string | null }): EvidenceItem {
  const id = over.documentId ?? nextId();
  return {
    documentId: id,
    downloadUrl: `#/${id}`,
    format: "pdf" as EvidenceFormat,
    uploadedBy: preparer,
    uploadedAt: "2025-06-02T09:00:00Z",
    evidenceClass: "main",
    disposition: "active",
    processingState: "extracted",
    haltReason: null,
    typeReviewBand: null,
    typeReviewReason: null,
    facilityState: "resolved",
    facilityId: null,
    facilityName: null,
    facilityCount: null,
    periodState: "resolved",
    periodStart: null,
    periodEnd: null,
    fieldsExpected: 0,
    fieldsExpectedDisplay: null,
    fieldsExtracted: 0,
    documentProperties: [],
    relationships: [],
    reviewArea: null,
    note: null,
    notes: [],
    answeredRequestNumber: null,
    arrivedSinceLastVisit: false,
    missingFields: [],
    ...over,
  };
}

function monthPeriod(mIdx: number, year = "2025") {
  const mm = String(mIdx + 1).padStart(2, "0");
  return {
    periodState: "resolved" as const,
    periodStart: `${year}-${mm}-01`,
    periodEnd: `${year}-${mm}-${MONTH_DAYS[mIdx]}`,
    periodLabel: `${MONTHS[mIdx]} ${year}`,
  };
}

function facilityFields(fac: { facilityId: string; name: string }) {
  return { facilityState: "resolved" as const, facilityId: fac.facilityId, facilityName: fac.name };
}

const docs: EvidenceItem[] = [];
const slug = (name: string) => name.split(" ")[0].toLowerCase();

// --- Electricity bills: monthly per facility (Scope 2). Tualatin is missing
//     Feb and Mar to plant the "facility missing two months" gap. ---
([FAC.tualatin, FAC.kent, FAC.modesto]).forEach((fac) => {
  MONTHS.forEach((_, i) => {
    if (fac.facilityId === FAC.tualatin.facilityId && (i === 1 || i === 2)) return; // missing Feb/Mar
    const p = monthPeriod(i);
    docs.push(
      base({
        documentId: `DOC-${slug(fac.name)}-elec-${MONTHS[i].toLowerCase()}`,
        filename: `${slug(fac.name)}_electric_${MONTHS[i].toLowerCase()}_2025.pdf`,
        detectedType: "Electricity bill",
        ...facilityFields(fac),
        periodState: p.periodState,
        periodStart: p.periodStart,
        periodEnd: p.periodEnd,
        fieldsExpected: 3,
        fieldsExpectedDisplay: 3,
        fieldsExtracted: 3,
        uploadedAt: `2025-${String(i + 1).padStart(2, "0")}-14T10:00:00Z`,
      })
    );
  });
});

// --- Natural gas bills: monthly per facility (Scope 1). ---
([FAC.tualatin, FAC.kent, FAC.modesto]).forEach((fac) => {
  MONTHS.forEach((_, i) => {
    const p = monthPeriod(i);
    docs.push(
      base({
        documentId: `DOC-${slug(fac.name)}-gas-${MONTHS[i].toLowerCase()}`,
        filename: `${slug(fac.name)}_gas_${MONTHS[i].toLowerCase()}_2025.pdf`,
        detectedType: "Natural gas bill",
        ...facilityFields(fac),
        periodState: p.periodState,
        periodStart: p.periodStart,
        periodEnd: p.periodEnd,
        fieldsExpected: 2,
        fieldsExpectedDisplay: 2,
        fieldsExtracted: 2,
        uploadedAt: `2025-${String(i + 1).padStart(2, "0")}-16T10:00:00Z`,
      })
    );
  });
});

// --- Meter readings / photos: monthly per facility. ---
([FAC.tualatin, FAC.kent, FAC.modesto]).forEach((fac) => {
  MONTHS.forEach((_, i) => {
    const p = monthPeriod(i);
    docs.push(
      base({
        filename: `${slug(fac.name)}_meter_${MONTHS[i].toLowerCase()}.jpg`,
        format: "image",
        detectedType: "Meter reading or meter photo",
        ...facilityFields(fac),
        periodState: p.periodState,
        periodStart: p.periodStart,
        periodEnd: p.periodEnd,
        fieldsExpected: 1,
        fieldsExpectedDisplay: 1,
        fieldsExtracted: 1,
      })
    );
  });
});

// --- Fleet fuel statements: quarterly per facility (Scope 1). ---
([FAC.tualatin, FAC.kent, FAC.modesto]).forEach((fac) => {
  ["Q1", "Q2", "Q3", "Q4"].forEach((q, qi) => {
    docs.push(
      base({
        filename: `${slug(fac.name)}_fleetcard_${q.toLowerCase()}_2025.pdf`,
        detectedType: "Fleet fuel statement",
        ...facilityFields(fac),
        periodState: "spans_multiple",
        periodStart: `2025-${String(qi * 3 + 1).padStart(2, "0")}-01`,
        periodEnd: `2025-${String(qi * 3 + 3).padStart(2, "0")}-30`,
        fieldsExpected: 2,
        fieldsExpectedDisplay: 2,
        fieldsExtracted: 2,
      })
    );
  });
});

// --- Other fuel invoices (propane deliveries). ---
["Feb", "May", "Aug", "Nov"].forEach((m, k) => {
  const fac = k % 2 === 0 ? FAC.modesto : FAC.kent;
  docs.push(
    base({
      filename: `${slug(fac.name)}_propane_${m.toLowerCase()}.pdf`,
      detectedType: "Other fuel invoice",
      ...facilityFields(fac),
      periodState: "resolved",
      periodStart: `2025-${String(MONTHS.indexOf(m) + 1).padStart(2, "0")}-05`,
      periodEnd: `2025-${String(MONTHS.indexOf(m) + 1).padStart(2, "0")}-05`,
      fieldsExpected: 1,
      fieldsExpectedDisplay: 1,
      fieldsExtracted: 1,
    })
  );
});

// --- Refrigerant service logs (Scope 1). ---
([FAC.tualatin, FAC.kent, FAC.modesto]).forEach((fac) => {
  docs.push(
    base({
      filename: `${slug(fac.name)}_refrigerant_service.pdf`,
      detectedType: "Refrigerant service log or refrigerant purchase invoice",
      ...facilityFields(fac),
      periodState: "spans_multiple",
      periodStart: "2025-01-01",
      periodEnd: "2025-12-31",
      fieldsExpected: 2,
      fieldsExpectedDisplay: 2,
      fieldsExtracted: 2,
    })
  );
});

// --- Energy management system exports. ---
([FAC.tualatin, FAC.kent]).forEach((fac) => {
  docs.push(
    base({
      filename: `${slug(fac.name)}_ems_export_2025.csv`,
      format: "csv",
      detectedType: "Energy management system export",
      ...facilityFields(fac),
      periodState: "spans_multiple",
      periodStart: "2025-01-01",
      periodEnd: "2025-12-31",
      fieldsExpected: 4,
      fieldsExpectedDisplay: 4,
      fieldsExtracted: 4,
    })
  );
});

// --- Renewable energy certificates / retirement statements. ---
["tualatin", "kent", "modesto"].forEach((s, k) => {
  const fac = [FAC.tualatin, FAC.kent, FAC.modesto][k];
  docs.push(
    base({
      filename: `${s}_rec_retirement_2025.pdf`,
      detectedType: "Renewable energy certificate or retirement statement",
      ...facilityFields(fac),
      periodState: "resolved",
      periodStart: "2025-01-01",
      periodEnd: "2025-12-31",
      fieldsExpected: 2,
      fieldsExpectedDisplay: 2,
      fieldsExtracted: 2,
    })
  );
});

// --- Power purchase agreement (entity). ---
docs.push(
  base({
    filename: "cascade_ppa_greenpower.pdf",
    detectedType: "Power purchase agreement or supplier contract",
    facilityState: "not_facility_scoped",
    periodState: "spans_multiple",
    periodStart: "2023-01-01",
    periodEnd: "2027-12-31",
    fieldsExpected: 3,
    fieldsExpectedDisplay: 3,
    fieldsExtracted: 3,
  })
);

// --- Supplier-specific factor documentation. ---
["green_tariff_letter", "supplier_factor_letter"].forEach((f) => {
  docs.push(
    base({
      filename: `${f}.pdf`,
      detectedType: "Supplier-specific factor documentation",
      facilityState: "not_facility_scoped",
      periodState: "resolved",
      periodStart: "2025-01-01",
      periodEnd: "2025-12-31",
      fieldsExpected: 2,
      fieldsExpectedDisplay: 2,
      fieldsExtracted: 2,
    })
  );
});

// --- Entity-level documents (no facility). ---
docs.push(
  base({
    filename: "cascade_org_boundary_statement.pdf",
    detectedType: "Organizational boundary statement",
    facilityState: "not_facility_scoped",
    periodState: "resolved",
    periodStart: "2025-01-01",
    periodEnd: "2025-12-31",
    fieldsExpected: 1,
    fieldsExpectedDisplay: 1,
    fieldsExtracted: 1,
  })
);
docs.push(
  base({
    filename: "cascade_facility_list.pdf",
    detectedType: "Facility list",
    facilityState: "not_facility_scoped",
    periodState: "resolved",
    periodStart: "2025-01-01",
    periodEnd: "2025-12-31",
    fieldsExpected: 1,
    fieldsExpectedDisplay: 1,
    fieldsExtracted: 1,
  })
);
docs.push(
  base({
    filename: "cascade_emission_factors_2025.pdf",
    detectedType: "Emission factor source list",
    facilityState: "not_facility_scoped",
    periodState: "resolved",
    periodStart: "2025-01-01",
    periodEnd: "2025-12-31",
    fieldsExpected: 3,
    fieldsExpectedDisplay: 3,
    fieldsExtracted: 3,
  })
);

// --- All-facility inventory workbook (covers all three facilities). ---
docs.push(
  base({
    documentId: "DOC-WORKBOOK",
    filename: "cascade_inventory_workbook_2025.xlsx",
    format: "xlsx",
    detectedType: "Inventory workbook",
    facilityState: "multiple",
    facilityCount: 3,
    facilityIds: [FAC.tualatin.facilityId, FAC.kent.facilityId, FAC.modesto.facilityId],
    periodState: "spans_multiple",
    periodStart: "2025-01-01",
    periodEnd: "2025-12-31",
    fieldsExpected: 18,
    fieldsExpectedDisplay: 18,
    fieldsExtracted: 18,
    note: "Client's own calculation · reconcile against extracted bills.",
    notes: [
      {
        id: "n-wb-1",
        author: "M. Osei",
        at: "2025-09-12T15:20:00Z",
        text: "Client's own calculation · reconcile against extracted bills.",
      },
    ],
  })
);

// ============================ PLANTED MESS ============================

// Two duplicate electricity bills (Tualatin, July) · duplicate of each other.
docs.push(
  base({
    documentId: "DOC-DUPE-A",
    filename: "tualatin_electric_jul_2025.pdf",
    detectedType: "Electricity bill",
    ...facilityFields(FAC.tualatin),
    periodState: "resolved",
    periodStart: "2025-07-01",
    periodEnd: "2025-07-31",
    fieldsExpected: 3,
    fieldsExpectedDisplay: 3,
    fieldsExtracted: 3,
    relationships: [{ kind: "duplicate", otherDocumentId: "DOC-DUPE-B" }],
    arrivedSinceLastVisit: true,
  })
);
docs.push(
  base({
    documentId: "DOC-DUPE-B",
    filename: "tualatin_electric_july_copy.pdf",
    detectedType: "Electricity bill",
    ...facilityFields(FAC.tualatin),
    periodState: "resolved",
    periodStart: "2025-07-01",
    periodEnd: "2025-07-31",
    fieldsExpected: 3,
    fieldsExpectedDisplay: 3,
    fieldsExtracted: 3,
    relationships: [{ kind: "duplicate", otherDocumentId: "DOC-DUPE-A" }],
    arrivedSinceLastVisit: true,
  })
);

// Prior-year inventory (period outside reporting year).
docs.push(
  base({
    documentId: "DOC-PRIOR",
    filename: "cascade_inventory_2024_final.pdf",
    detectedType: "Prior-year inventory or report",
    facilityState: "not_facility_scoped",
    periodState: "resolved",
    periodStart: "2024-01-01",
    periodEnd: "2024-12-31",
    fieldsExpected: 1,
    fieldsExpectedDisplay: 1,
    fieldsExtracted: 1,
  })
);
// Wrong-year electricity bill (Dec 2024) mixed into the package.
docs.push(
  base({
    documentId: "DOC-WRONGYEAR",
    filename: "kent_electric_dec_2024.pdf",
    detectedType: "Electricity bill",
    ...facilityFields(FAC.kent),
    periodState: "resolved",
    periodStart: "2024-12-01",
    periodEnd: "2024-12-31",
    fieldsExpected: 3,
    fieldsExpectedDisplay: 3,
    fieldsExtracted: 3,
  })
);

// Unreadable scan (blocked).
docs.push(
  base({
    documentId: "DOC-BLOCKED",
    filename: "scan_0417.pdf",
    detectedType: "Electricity bill",
    processingState: "blocked",
    haltReason: "Scan is unreadable · no extractable text on any page.",
    documentProperties: ["poor_scan"],
    ...facilityFields(FAC.modesto),
    periodState: "unresolved",
    fieldsExpected: 3,
    fieldsExpectedDisplay: 3,
    fieldsExtracted: 0,
    arrivedSinceLastVisit: true,
  })
);

// Two unclassifiable files (type unresolved, sit first).
docs.push(
  base({
    documentId: "DOC-UNCLASS-1",
    filename: "IMG_2231.jpg",
    format: "image",
    detectedType: null,
    typeReviewBand: "cannot_determine",
    typeReviewReason: "Classifier could not match this file to any type.",
    processingState: "ingested",
    facilityState: "unresolved",
    periodState: "unresolved",
    fieldsExpected: 0,
    fieldsExpectedDisplay: null,
    fieldsExtracted: 0,
    arrivedSinceLastVisit: true,
  })
);
docs.push(
  base({
    documentId: "DOC-UNCLASS-2",
    filename: "notes_from_client.docx",
    format: "other",
    detectedType: null,
    typeReviewBand: "cannot_determine",
    typeReviewReason: "Classifier could not match this file to any type.",
    processingState: "ingested",
    facilityState: "unresolved",
    periodState: "unresolved",
    fieldsExpected: 0,
    fieldsExpectedDisplay: null,
    fieldsExtracted: 0,
  })
);

// Partially extracted gas bill (light red; one field not found).
docs.push(
  base({
    documentId: "DOC-PARTIAL",
    filename: "kent_gas_sep_2025.pdf",
    detectedType: "Natural gas bill",
    ...facilityFields(FAC.kent),
    periodState: "resolved",
    periodStart: "2025-09-01",
    periodEnd: "2025-09-30",
    fieldsExpected: 2,
    fieldsExpectedDisplay: 2,
    fieldsExtracted: 1,
    missingFields: ["Service period end date"],
    arrivedSinceLastVisit: true,
  })
);

// Conflicting pair: a meter photo whose read conflicts with the bill.
docs.push(
  base({
    documentId: "DOC-CONFLICT-A",
    filename: "modesto_meter_aug_photo.jpg",
    format: "image",
    detectedType: "Meter reading or meter photo",
    ...facilityFields(FAC.modesto),
    periodState: "resolved",
    periodStart: "2025-08-01",
    periodEnd: "2025-08-31",
    fieldsExpected: 1,
    fieldsExpectedDisplay: 1,
    fieldsExtracted: 1,
    relationships: [{ kind: "conflicting_value", otherDocumentId: "DOC-CONFLICT-B" }],
  })
);
docs.push(
  base({
    documentId: "DOC-CONFLICT-B",
    filename: "modesto_electric_aug_2025.pdf",
    detectedType: "Electricity bill",
    ...facilityFields(FAC.modesto),
    periodState: "resolved",
    periodStart: "2025-08-01",
    periodEnd: "2025-08-31",
    fieldsExpected: 3,
    fieldsExpectedDisplay: 3,
    fieldsExtracted: 3,
    relationships: [{ kind: "conflicting_value", otherDocumentId: "DOC-CONFLICT-A" }],
  })
);

// Supersede: a corrected re-upload supersedes an earlier bill.
docs.push(
  base({
    documentId: "DOC-OLD",
    filename: "tualatin_gas_apr_2025.pdf",
    detectedType: "Natural gas bill",
    ...facilityFields(FAC.tualatin),
    periodState: "resolved",
    periodStart: "2025-04-01",
    periodEnd: "2025-04-30",
    fieldsExpected: 2,
    fieldsExpectedDisplay: 2,
    fieldsExtracted: 2,
    relationships: [{ kind: "superseded_by", otherDocumentId: "DOC-NEW" }],
  })
);
docs.push(
  base({
    documentId: "DOC-NEW",
    filename: "tualatin_gas_apr_2025_corrected.pdf",
    detectedType: "Natural gas bill",
    ...facilityFields(FAC.tualatin),
    periodState: "resolved",
    periodStart: "2025-04-01",
    periodEnd: "2025-04-30",
    fieldsExpected: 2,
    fieldsExpectedDisplay: 2,
    fieldsExtracted: 2,
    relationships: [{ kind: "supersedes", otherDocumentId: "DOC-OLD" }],
    answeredRequestNumber: 2,
    arrivedSinceLastVisit: true,
    note: "Client re-sent April gas bill with the corrected total.",
    notes: [
      { id: "n-new-1", author: "M. Osei", at: "2025-09-13T11:05:00Z", text: "Client re-sent April gas bill with the corrected total." },
    ],
  })
);

// ============================ STRESSORS ============================

// Mileage/expense report · 312 rows from one file.
docs.push(
  base({
    documentId: "DOC-MILEAGE",
    filename: "mileage_reimbursement_2025.xlsx",
    format: "xlsx",
    detectedType: "Mileage or expense report",
    ...facilityFields(FAC.tualatin),
    periodState: "spans_multiple",
    periodStart: "2025-01-01",
    periodEnd: "2025-12-31",
    fieldsExpected: 312,
    fieldsExpectedDisplay: 312,
    fieldsExtracted: 312,
    arrivedSinceLastVisit: true,
    note: "312 trip rows · expect the value list to be unusable one-card-per-value.",
    notes: [
      { id: "n-mile-1", author: "M. Osei", at: "2025-09-14T09:10:00Z", text: "312 trip rows · expect the value list to be unusable one-card-per-value." },
    ],
  })
);

// Supplier roster · 218 entries.
docs.push(
  base({
    documentId: "DOC-ROSTER",
    filename: "supplier_roster_FY2025.csv",
    format: "csv",
    detectedType: "Supplier roster",
    facilityState: "not_facility_scoped",
    periodState: "resolved",
    periodStart: "2025-01-01",
    periodEnd: "2025-12-31",
    fieldsExpected: 218,
    fieldsExpectedDisplay: 218,
    fieldsExtracted: 218,
    arrivedSinceLastVisit: true,
  })
);

export const manufacturerEvidence: EvidenceItem[] = docs;

/** A couple of supportive documents (enter the workpaper, never extracted). */
export const manufacturerSupportive: EvidenceItem[] = [
  base({
    documentId: "DOC-SUP-1",
    filename: "cascade_site_map.pdf",
    detectedType: "Facility list",
    evidenceClass: "supportive",
    facilityState: "not_facility_scoped",
    periodState: "resolved",
    periodStart: "2025-01-01",
    periodEnd: "2025-12-31",
    reviewArea: "Boundary and completeness",
    note: "Site map used to confirm the facility list is complete.",
  }),
];

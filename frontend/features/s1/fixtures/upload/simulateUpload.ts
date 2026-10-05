import type { EngagementConfig } from "../../types/engagement";
import type { EvidenceItem, EvidenceFormat } from "../../types/evidence";

/**
 * Fixture-mode upload: turn a dropped File into an Evidence Workspace row that
 * starts "uploading" and then progresses. No backend — the swap to a real
 * upload happens in one place (S1WorkpaperApp.handleUploadFiles).
 */

let uploadSeq = 0;

const reviewer = { id: "local_reviewer", name: "You", actorType: "reviewer" as const };

function formatFor(name: string): EvidenceFormat {
  const lower = name.toLowerCase();
  if (lower.endsWith(".pdf")) return "pdf";
  if (/\.(png|jpe?g|gif|tiff?|heic)$/.test(lower)) return "image";
  if (lower.endsWith(".xlsx") || lower.endsWith(".xls")) return "xlsx";
  if (lower.endsWith(".csv")) return "csv";
  return "other";
}

/** A freshly dropped file: uploading, type not yet known, facility unresolved. */
export function makeUploadItem(file: File): EvidenceItem {
  uploadSeq += 1;
  const id = `DOC-UP-${String(uploadSeq).padStart(3, "0")}`;
  return {
    documentId: id,
    filename: file.name,
    downloadUrl: `#/${id}`,
    format: formatFor(file.name),
    uploadedBy: reviewer,
    uploadedAt: new Date().toISOString(),
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
    fieldsExpected: 0,
    fieldsExpectedDisplay: null,
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

/**
 * What the classifier "found" once processing finishes — keyword-guessed from
 * the file name, with the facility guessed from a Setup facility name prefix.
 */
export function classifyGuess(filename: string, engagement: EngagementConfig): Partial<EvidenceItem> {
  const lower = filename.toLowerCase();
  const facility = engagement.facilities.find((f) => lower.startsWith(f.name.split(" ")[0].toLowerCase()));
  const facilityFields: Partial<EvidenceItem> = facility
    ? { facilityState: "resolved", facilityId: facility.facilityId, facilityName: facility.name }
    : {};

  const type = guessType(lower);
  if (!type) {
    // could not classify — sits under "Type unresolved" until someone sets it.
    return { processingState: "ingested", detectedType: null, typeReviewBand: "cannot_determine", ...facilityFields };
  }
  return {
    processingState: "extracted",
    detectedType: type.name,
    fieldsExpected: type.fields,
    fieldsExpectedDisplay: type.fields,
    fieldsExtracted: type.fields,
    ...facilityFields,
  };
}

function guessType(lower: string): { name: string; fields: number } | null {
  if (/electric/.test(lower)) return { name: "Electricity bill", fields: 3 };
  if (/gas/.test(lower)) return { name: "Natural gas bill", fields: 2 };
  if (/fleet|fuelcard/.test(lower)) return { name: "Fleet fuel statement", fields: 2 };
  if (/propane|diesel|fuel/.test(lower)) return { name: "Other fuel invoice", fields: 1 };
  if (/meter/.test(lower)) return { name: "Meter reading or meter photo", fields: 1 };
  if (/refrig/.test(lower)) return { name: "Refrigerant service log or refrigerant purchase invoice", fields: 2 };
  if (/workbook|inventory/.test(lower)) return { name: "Inventory workbook", fields: 18 };
  return null;
}

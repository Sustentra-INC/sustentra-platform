import type { Actor } from "./engagement";
import type {
  FacilityState,
  PeriodState,
  ProcessingState,
  TypeReviewBand,
  EvidenceDisposition,
} from "./states";

export type EvidenceClass = "main" | "supportive";
export type EvidenceFormat = "pdf" | "image" | "xlsx" | "csv" | "other";

export type RelationshipKind =
  | "duplicate"
  | "superseded_by"
  | "supersedes"
  | "conflicting_value";

export type DocumentProperty =
  | "poor_scan"
  | "foreign_language"
  | "password_protected";

export interface EvidenceRelationship {
  kind: RelationshipKind;
  otherDocumentId: string;
  fieldKey?: string;
}

export interface NoteEntry {
  id: string;
  author: string;
  /** ISO timestamp. */
  at: string;
  text: string;
}

export interface EvidenceItem {
  documentId: string;
  filename: string;
  downloadUrl?: string;
  format: EvidenceFormat;
  uploadedBy: Actor;
  uploadedAt: string;
  evidenceClass: EvidenceClass;
  disposition: EvidenceDisposition;
  processingState: ProcessingState;
  haltReason: string | null;
  detectedType: string | null;
  typeReviewBand: TypeReviewBand;
  typeReviewReason: string | null;
  facilityState: FacilityState;
  facilityId: string | null;
  facilityName: string | null;
  facilityCount: number | null;
  /**
   * Every facility this file covers, by id. Set for multi-facility files (a
   * workbook covering three sites) so the file appears under each of those
   * facilities in the filter and the Screen 3 navigator, not only under
   * "Multiple facilities". Optional; the backend adapter does not set it yet.
   */
  facilityIds?: string[];
  periodState: PeriodState;
  periodStart: string | null;
  periodEnd: string | null;
  fieldsExpected: number;
  fieldsExpectedDisplay: number | null;
  fieldsExtracted: number;
  documentProperties: DocumentProperty[];
  relationships: EvidenceRelationship[];
  reviewArea: string | null;
  note: string | null;

  // --- Revised-spec (09/16) additions. All optional so the backend adapter,
  // which does not yet populate them, keeps compiling. ---

  /** Full note history; the column shows the latest, the row expansion all. */
  notes?: NoteEntry[];
  /** How the file arrived: null = uploaded; a number = answered request n. */
  answeredRequestNumber?: number | null;
  /** Whether the file arrived since the verifier's last visit (header count). */
  arrivedSinceLastVisit?: boolean;
  /** For "partially extracted": the required fields the extractor did not find. */
  missingFields?: string[];
}

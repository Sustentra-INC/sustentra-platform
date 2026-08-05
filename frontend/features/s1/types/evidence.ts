import type { Actor } from "./engagement";
import type {
  FacilityState,
  PeriodState,
  ProcessingState,
  TypeReviewBand,
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

export interface EvidenceItem {
  documentId: string;
  filename: string;
  downloadUrl?: string;
  format: EvidenceFormat;
  uploadedBy: Actor;
  uploadedAt: string;
  evidenceClass: EvidenceClass;
  processingState: ProcessingState;
  haltReason: string | null;
  detectedType: string | null;
  typeReviewBand: TypeReviewBand;
  typeReviewReason: string | null;
  facilityState: FacilityState;
  facilityId: string | null;
  facilityName: string | null;
  facilityCount: number | null;
  periodState: PeriodState;
  periodStart: string | null;
  periodEnd: string | null;
  fieldsExpected: number;
  fieldsExtracted: number;
  documentProperties: DocumentProperty[];
  relationships: EvidenceRelationship[];
  reviewArea: string | null;
  note: string | null;
}

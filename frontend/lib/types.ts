export type ProcessingStatus = "not_started" | "queued" | "in_progress" | "completed" | "failed";

export interface DocumentRecord {
  document_id: string;
  engagement_id: string;
  file_name: string;
  processing_status: ProcessingStatus;
}

export interface SourceReference {
  source_reference_id: string;
  document_id: string;
  page_number?: number | null;
  sheet_name?: string | null;
  cell_or_range?: string | null;
  text_snippet?: string | null;
}

export interface EvidenceField {
  field_name: string;
  extracted_value: string | number | boolean | null;
  approved_value: string | number | boolean | null;
  unit?: string | null;
  decision: "accepted" | "edited" | "rejected" | "clarification_requested";
  source_reference?: SourceReference;
}

export interface EvidenceRecord {
  evidence_id: string;
  engagement_id: string;
  document_id: string;
  evidence_type: string;
  review_status: string;
  fields: EvidenceField[];
}

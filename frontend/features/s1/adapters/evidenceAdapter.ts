import type { EvidenceItem } from "../types";
import { apiUrl } from "../../../lib/api/client";

export interface BackendDocumentLike {
  document_id: string;
  file_name: string;
  mime_type?: string | null;
  uploaded_by: string;
  uploaded_at: string;
  processing_status: string;
  evidence_id?: string | null;
}

export function mapBackendDocumentToEvidenceItem(
  document: BackendDocumentLike,
  summary?: {
    canonical_type_id?: string | null;
    target_count?: number | null;
    candidate_count?: number | null;
    found_candidate_count?: number | null;
    status?: string | null;
    errors?: string[] | null;
  } | null
): EvidenceItem {
  const hasType = Boolean(summary?.canonical_type_id);
  const processingState =
    document.processing_status === "failed"
      ? "blocked"
      : document.processing_status === "completed"
        ? "extracted"
        : document.processing_status === "not_started"
          ? "not_ingested"
          : "ingested";

  return {
    documentId: document.document_id,
    filename: document.file_name,
    downloadUrl: apiUrl(`/v1/documents/${document.document_id}/download`),
    format: document.file_name.endsWith(".xlsx") ? "xlsx" : "pdf",
    uploadedBy: { id: document.uploaded_by, name: document.uploaded_by, actorType: "preparer" },
    uploadedAt: document.uploaded_at,
    evidenceClass: "main",
    processingState,
    haltReason:
      document.processing_status === "failed"
        ? summary?.errors?.[0] ?? "Processing failed. Retry available."
        : null,
    detectedType: summary?.canonical_type_id ?? null,
    typeReviewBand: hasType ? "auto_accepted" : null,
    typeReviewReason: hasType ? null : null,
    facilityState: "unresolved",
    facilityId: null,
    facilityName: null,
    facilityCount: null,
    periodState: "unresolved",
    periodStart: null,
    periodEnd: null,
    fieldsExpected: Number(summary?.target_count ?? summary?.candidate_count ?? 0),
    fieldsExtracted: Number(summary?.found_candidate_count ?? 0),
    documentProperties: [],
    relationships: [],
    reviewArea: null,
    note: null,
  };
}

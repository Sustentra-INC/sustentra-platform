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
    warnings?: string[] | null;
    errors?: string[] | null;
  } | null
): EvidenceItem {
  const hasType = Boolean(summary?.canonical_type_id);
  const summaryWarnings = summary?.warnings ?? [];
  const noExtractionTargets =
    summary?.status === "partial" &&
    Number(summary?.candidate_count ?? 0) === 0 &&
    Number(summary?.target_count ?? 0) === 0;
  const processingState =
    document.processing_status === "failed"
      ? "blocked"
      : noExtractionTargets
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
    format: resolveFormat(document.file_name, document.mime_type),
    uploadedBy: { id: document.uploaded_by, name: document.uploaded_by, actorType: "preparer" },
    uploadedAt: document.uploaded_at,
    evidenceClass: "main",
    processingState,
    haltReason:
      document.processing_status === "failed" || noExtractionTargets
        ? summary?.errors?.[0] ??
          summaryWarnings[0] ??
          "No extraction template exists for this document type."
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

export function inlineDocumentUrl(documentId: string): string {
  return apiUrl(`/v1/documents/${documentId}/preview`);
}

function resolveFormat(filename: string, mimeType?: string | null): EvidenceItem["format"] {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".xlsx") || lower.endsWith(".xls")) return "xlsx";
  if (lower.endsWith(".csv") || mimeType === "text/csv") return "csv";
  if (lower.endsWith(".png") || lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image";
  if (lower.endsWith(".pdf") || mimeType === "application/pdf") return "pdf";
  return "other";
}

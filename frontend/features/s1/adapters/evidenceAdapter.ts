import type { EvidenceItem } from "../types";
import { apiUrl } from "../../../lib/api/client";
import { HALT_REASONS } from "../constants/copy";

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
    canonical_type_name?: string | null;
    type_name?: string | null;
    display_name?: string | null;
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

  const fieldsExpected = Number(summary?.target_count ?? summary?.candidate_count ?? 0);

  return {
    documentId: document.document_id,
    filename: document.file_name,
    downloadUrl: apiUrl(`/v1/documents/${document.document_id}/download`),
    format: resolveFormat(document.file_name, document.mime_type),
    uploadedBy: { id: document.uploaded_by, name: document.uploaded_by, actorType: "preparer" },
    uploadedAt: document.uploaded_at,
    evidenceClass: "main",
    disposition: "active",
    processingState,
    haltReason:
      document.processing_status === "failed" || noExtractionTargets
        ? mapHaltReason({
            noExtractionTargets,
            details: [...(summary?.errors ?? []), ...summaryWarnings],
          })
        : null,
    detectedType: resolveCanonicalTypeDisplayName(summary),
    typeReviewBand: hasType ? "auto_accepted" : null,
    typeReviewReason: hasType ? null : null,
    facilityState: "unresolved",
    facilityId: null,
    facilityName: null,
    facilityCount: null,
    periodState: "unresolved",
    periodStart: null,
    periodEnd: null,
    fieldsExpected,
    fieldsExpectedDisplay: fieldsExpected === 0 ? null : fieldsExpected,
    fieldsExtracted: Number(summary?.found_candidate_count ?? 0),
    documentProperties: [],
    relationships: [],
    reviewArea: null,
    note: null,
  };
}

const CANONICAL_TYPE_DISPLAY_NAMES: Record<string, string> = {
  "CT-S1-FUELQTY": "Stationary fuel consumption record",
  "CT-S1-MOBFUEL": "Mobile fuel consumption record",
};

export function resolveCanonicalTypeDisplayName(
  summary?: {
    canonical_type_id?: string | null;
    canonical_type_name?: string | null;
    type_name?: string | null;
    display_name?: string | null;
  } | null
): string | null {
  const backendName = summary?.canonical_type_name ?? summary?.type_name ?? summary?.display_name;
  if (backendName) return backendName;

  const canonicalTypeId = summary?.canonical_type_id;
  if (!canonicalTypeId) return null;
  return CANONICAL_TYPE_DISPLAY_NAMES[canonicalTypeId] ?? "Unmapped document type";
}

export function mapHaltReason({
  noExtractionTargets,
  details,
}: {
  noExtractionTargets: boolean;
  details: string[];
}): string {
  if (noExtractionTargets) return HALT_REASONS.noTemplate;

  const detail = details.find(Boolean)?.toLowerCase() ?? "";
  if (detail.includes("unsupported") || detail.includes("format")) {
    return HALT_REASONS.unsupportedFormat;
  }
  if (detail.includes("unreadable") || detail.includes("could not be read")) {
    return HALT_REASONS.unreadable;
  }
  if (detail.includes("ocr") || detail.includes("text could not be extracted")) {
    return HALT_REASONS.ocrFailed;
  }
  if (detail.includes("multi-facility") || detail.includes("multiple facilit")) {
    return HALT_REASONS.multiFacility;
  }
  if (detail) {
    console.warn("Unmapped S1 halt reason from backend", detail);
  }
  return HALT_REASONS.pipeline;
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

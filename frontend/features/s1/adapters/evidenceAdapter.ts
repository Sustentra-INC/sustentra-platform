import type { EvidenceItem } from "../types";
import { apiPath } from "../../../lib/api";
import { AI_TYPE, HALT_REASONS } from "../constants/copy";
import type { ProcessingRunView } from "../api/processingRuns";

export interface BackendDocumentLike {
  document_id: string;
  file_name: string;
  mime_type?: string | null;
  uploaded_by: string;
  uploaded_at: string;
  processing_status: string;
  evidence_id?: string | null;
  /** The read the upload queued, when the API runs reads in the background. */
  processing_run?: ProcessingRunView | null;
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
    /** Why the pipeline stopped before reviewable candidates (unreadable / unsupported). */
    halt_reason?: { code?: string | null; message?: string | null } | null;
    /** "ai" when Claude set the type, which the reviewer confirms. */
    canonical_type_source?: string | null;
    /** What Claude cited for the type (present when it set it, or disagreed with the rules). */
    ai_routing?: {
      canonical_type_id: string;
      quote: string;
      page_number?: number | null;
      used: boolean;
      disagrees?: boolean;
    } | null;
  } | null
): EvidenceItem {
  const hasType = Boolean(summary?.canonical_type_id);
  const routing = summary?.ai_routing ?? null;
  const aiSetType = hasType && summary?.canonical_type_source === "ai" && routing?.used === true;
  const summaryWarnings = summary?.warnings ?? [];
  const noExtractionTargets =
    summary?.status === "partial" &&
    Number(summary?.candidate_count ?? 0) === 0 &&
    Number(summary?.target_count ?? 0) === 0;
  const halt = haltReasonFromCode(summary?.halt_reason?.code, summary?.halt_reason?.message);
  const unreadPages = unreadPagesFromWarnings(summaryWarnings);
  const processingState =
    document.processing_status === "failed" || halt
      ? "blocked"
      : noExtractionTargets
        ? "blocked"
      : document.processing_status === "completed"
        ? "extracted"
        : document.processing_status === "not_started"
          ? "not_ingested"
          : "ingested";

  // A multi-record document (12 monthly readings, several fuel purchases) has one set of
  // targets per record, so the expected count is every candidate, not one record's targets.
  const fieldsExpected = Math.max(Number(summary?.candidate_count ?? 0), Number(summary?.target_count ?? 0));

  return {
    documentId: document.document_id,
    filename: document.file_name,
    downloadUrl: apiPath(`/documents/${encodeURIComponent(document.document_id)}/download`),
    format: resolveFormat(document.file_name, document.mime_type),
    uploadedBy: { id: document.uploaded_by, name: document.uploaded_by, actorType: "preparer" },
    uploadedAt: document.uploaded_at,
    evidenceClass: "main",
    disposition: "active",
    processingState,
    haltReason: halt
      ? halt
      : document.processing_status === "failed" || noExtractionTargets
        ? mapHaltReason({
            noExtractionTargets,
            details: [...(summary?.errors ?? []), ...summaryWarnings],
          })
        : null,
    detectedType: resolveCanonicalTypeDisplayName(summary),
    typeReviewBand: aiSetType ? "needs_review" : hasType ? "auto_accepted" : null,
    typeReviewReason: aiSetType ? AI_TYPE.suggested : null,
    ...(routing && (aiSetType || routing.disagrees)
      ? {
          aiType: {
            quote: routing.quote,
            page: routing.page_number ?? null,
            typeName:
              resolveCanonicalTypeDisplayName({ canonical_type_id: routing.canonical_type_id }) ?? "another type",
            used: routing.used,
            disagrees: Boolean(routing.disagrees),
          },
        }
      : {}),
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
    unreadPages,
  };
}

const CANONICAL_TYPE_DISPLAY_NAMES: Record<string, string> = {
  "CT-S1-FUELQTY": "Stationary fuel consumption record",
  "CT-S1-MOBFUEL": "Mobile fuel consumption record",
  "CT-S1-REFRSVC": "Refrigerant service record",
  "CT-S2-ELEC": "Purchased electricity record",
  "CT-S2-THERMAL": "Purchased steam, heat or cooling record",
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

/** The page ranges a chunked read could not read, as the server wrote them ("11-20, 51"), from the
 *  pipeline run's `pages_unread: Pages <ranges> could not be read...` warning. No arithmetic here. */
export function unreadPagesFromWarnings(warnings: string[]): string | null {
  for (const warning of warnings) {
    const match = /^pages_unread: Pages (.+?) could not be read/.exec(warning);
    if (match) return match[1];
  }
  return null;
}

/** The pipeline's structured halt (pipeline_run.halt_reason.code), when it gives one. */
export function haltReasonFromCode(code: string | null | undefined, message?: string | null): string | null {
  if (code === "document_too_long") return message?.trim() || HALT_REASONS.documentTooLong;
  if (code === "unreadable_document") return HALT_REASONS.unreadable;
  if (code === "ocr_required") return HALT_REASONS.ocrRequired;
  if (code === "password_protected") return HALT_REASONS.passwordProtected;
  if (code === "unsupported_document") return HALT_REASONS.typeUnknown;
  return null;
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
  return apiPath(`/documents/${encodeURIComponent(documentId)}/preview`);
}

function resolveFormat(filename: string, mimeType?: string | null): EvidenceItem["format"] {
  const lower = filename.toLowerCase();
  if (lower.endsWith(".xlsx") || lower.endsWith(".xlsm") || lower.endsWith(".xls")) return "xlsx";
  if (lower.endsWith(".csv") || mimeType === "text/csv") return "csv";
  if (lower.endsWith(".png") || lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image";
  if (lower.endsWith(".pdf") || mimeType === "application/pdf") return "pdf";
  if (lower.endsWith(".docx")) return "docx";
  return "other";
}

/** The batch API words a halt as one sentence with no code. The internal wording of the
 *  unsupported-type halt ("the closest match was CT-S1-..., with confidence 0.48") is never shown:
 *  it becomes the plain sentence. The structured code is used wherever the API gives one
 *  (see haltReasonFromCode); this prefix check is only for the batch sentence, which has none. */
export function plainBatchHalt(message: string | null | undefined): string | null {
  const text = message?.trim();
  if (!text) return null;
  if (/^Unsupported document type\b/i.test(text)) return HALT_REASONS.typeUnknown;
  return text;
}

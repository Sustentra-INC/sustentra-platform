import { apiRequest, apiUrl } from "../../../lib/api/client";
import { mapBackendDocumentToEvidenceItem, type BackendDocumentLike } from "../adapters/evidenceAdapter";
import {
  decodeReviewCandidateToken,
  mapBackendCandidateToExtractedField,
  type BackendExtractionCandidateLike,
} from "../adapters/fieldAdapter";
import type { EvidenceItem, ExtractedField } from "../types";
import { HALT_REASONS } from "../constants/copy";

export interface PipelineRunSummary {
  evidence_id: string;
  document_id: string;
  canonical_type_id: string | null;
  target_count: number;
  candidate_count: number;
  found_candidate_count: number;
  status: string;
  warnings?: string[];
  errors?: string[];
}

export interface BackendExtractionResult {
  evidence_id: string;
  document_id: string;
  canonical_type_id: string | null;
  candidate_count: number;
  items: BackendExtractionCandidateLike[];
}

interface BackendReviewDecision {
  candidate_id: string;
  field_name: string;
  decision: "accepted" | "edited" | "rejected" | "needs_more_evidence";
  reviewed_value: string | number | boolean | null;
}

export async function listWorkspaceEvidence(engagementId: string): Promise<{
  evidence: EvidenceItem[];
  fields: ExtractedField[];
}> {
  const documents = await apiRequest<{ items: BackendDocumentLike[] }>(
    `/v1/engagements/${encodeURIComponent(engagementId)}/documents`
  );

  const enriched = await Promise.all(
    documents.items.map(async (document) => {
      const latestRun = document.evidence_id
        ? await apiMaybe<PipelineRunSummary>(
            `/v1/pipeline/evidence/${encodeURIComponent(document.evidence_id)}/latest-run`
          )
        : null;
      const extractionResult = await apiMaybe<BackendExtractionResult>(
        `/v1/documents/${encodeURIComponent(document.document_id)}/extraction-result/latest`
      );
      const reviews = await apiMaybe<BackendReviewDecision[]>(
        `/v1/documents/${encodeURIComponent(document.document_id)}/reviews`
      );
      const canonicalTypeId = extractionResult?.canonical_type_id ?? latestRun?.canonical_type_id ?? null;
      const latestReviewByCandidate = new Map<string, BackendReviewDecision>();
      for (const review of reviews ?? []) {
        latestReviewByCandidate.set(review.candidate_id, review);
      }

      return {
        evidence: mapBackendDocumentToEvidenceItem(document, latestRun),
        fields:
          extractionResult?.items.map((candidate) => {
            const field = mapBackendCandidateToExtractedField(candidate, canonicalTypeId);
            const review = candidate.candidate_id
              ? latestReviewByCandidate.get(candidate.candidate_id)
              : undefined;
            if (!review) return field;
            if (review.decision === "accepted") {
              return { ...field, reviewStatus: "accepted" as const };
            }
            if (review.decision === "edited") {
              return {
                ...field,
                correctedValue:
                  review.reviewed_value === null || review.reviewed_value === undefined
                    ? null
                    : String(review.reviewed_value),
                reviewStatus: field.value === null ? ("keyed_by_reviewer" as const) : ("corrected" as const),
              };
            }
            return field;
          }) ?? [],
      };
    })
  );

  return {
    evidence: enriched.map((item) => item.evidence),
    fields: enriched.flatMap((item) => item.fields),
  };
}

export async function uploadDocument(engagementId: string, file: File): Promise<BackendDocumentLike> {
  const body = new FormData();
  body.append("file", file);
  body.append("uploaded_by", "local_reviewer");
  body.append("document_role", "source_evidence");

  return apiRequest<BackendDocumentLike>(
    `/v1/engagements/${encodeURIComponent(engagementId)}/documents/upload`,
    {
      method: "POST",
      body,
    }
  );
}

export async function processDocument(documentId: string): Promise<void> {
  await apiRequest(`/v1/documents/${encodeURIComponent(documentId)}/pipeline/process`, {
    method: "POST",
    body: JSON.stringify({ persist_run: true }),
  });
}

export async function submitFieldReview({
  field,
  decision,
  reviewedValue,
  reviewerNote,
}: {
  field: ExtractedField;
  decision: "accepted" | "edited";
  reviewedValue?: string | null;
  reviewerNote?: string | null;
}): Promise<void> {
  const candidate = field.reviewToken ? decodeReviewCandidateToken(field.reviewToken) : null;
  const evidenceId = typeof candidate?.evidence_id === "string" ? candidate.evidence_id : null;
  const fieldName = typeof candidate?.field_name === "string" ? candidate.field_name : null;
  if (!candidate || !evidenceId || !fieldName) return;

  await apiRequest(`/v1/evidence/${encodeURIComponent(evidenceId)}/fields/${encodeURIComponent(fieldName)}/review`, {
    method: "PUT",
    body: JSON.stringify({
      candidate,
      decision,
      reviewer_id: "local_reviewer",
      reviewed_value: decision === "edited" ? reviewedValue : undefined,
      reviewer_note: reviewerNote,
    }),
  });
}

export function downloadUrl(documentId: string): string {
  return apiUrl(`/v1/documents/${encodeURIComponent(documentId)}/download`);
}

async function apiMaybe<T>(path: string): Promise<T | null> {
  const response = await fetch(apiUrl(path), { cache: "no-store" });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`API request failed: ${response.status}`);
  return response.json() as Promise<T>;
}

export function userFacingApiError(error: unknown): string {
  if (!(error instanceof Error)) return "Backend request failed.";
  if (error.message.includes(HALT_REASONS.unsupportedFormat)) return HALT_REASONS.unsupportedFormat;
  if (error.message.includes(HALT_REASONS.unreadable)) return HALT_REASONS.unreadable;
  return error.message;
}

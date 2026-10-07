import { api, ApiError, apiMaybe, apiPath } from "../../../lib/api";
import { lastRealm, signInPath } from "../../auth/lastRealm";
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

/**
 * S1 workpaper data seam (FE-007). Every call goes through the same-origin cookie
 * client (`lib/api.ts` → `/api/v1/*`), so the `__Host-session` cookie rides along
 * and the API scopes the data to the caller's org (SEC-001). A 401 means the
 * session ended: see `isSessionEnded` / `signInAgainPath`.
 */

/** The signed-in user, as the workpaper needs it. */
export interface SignedInUser {
  email: string;
  role: "provider_admin" | "org_admin" | "org_member";
  org_slug?: string | null;
}

/** Check the session up front so a signed-out visitor is sent to log in even
 *  before any engagement data is requested. Throws `ApiError` (401) when signed out. */
export function getSignedInUser(): Promise<SignedInUser> {
  return api<SignedInUser>("/auth/me");
}

export async function listWorkspaceEvidence(engagementId: string): Promise<{
  evidence: EvidenceItem[];
  fields: ExtractedField[];
}> {
  const documents = await api<{ items: BackendDocumentLike[] }>(
    `/engagements/${encodeURIComponent(engagementId)}/documents`
  );

  const enriched = await Promise.all(
    documents.items.map(async (document) => {
      const latestRun = document.evidence_id
        ? await apiMaybe<PipelineRunSummary>(
            `/pipeline/evidence/${encodeURIComponent(document.evidence_id)}/latest-run`
          )
        : null;
      const extractionResult = await apiMaybe<BackendExtractionResult>(
        `/documents/${encodeURIComponent(document.document_id)}/extraction-result/latest`
      );
      const reviews = await apiMaybe<BackendReviewDecision[]>(
        `/documents/${encodeURIComponent(document.document_id)}/reviews`
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
  body.append("document_role", "source_evidence");

  return api<BackendDocumentLike>(`/engagements/${encodeURIComponent(engagementId)}/documents/upload`, {
    method: "POST",
    body,
  });
}

export async function processDocument(documentId: string): Promise<void> {
  await api(`/documents/${encodeURIComponent(documentId)}/pipeline/process`, {
    method: "POST",
    body: { persist_run: true },
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

  await api(`/evidence/${encodeURIComponent(evidenceId)}/fields/${encodeURIComponent(fieldName)}/review`, {
    method: "PUT",
    // The reviewer is the signed-in user; the API records it from the session.
    body: {
      candidate,
      decision,
      reviewed_value: decision === "edited" ? reviewedValue : undefined,
      reviewer_note: reviewerNote,
    },
  });
}

export function downloadUrl(documentId: string): string {
  return apiPath(`/documents/${encodeURIComponent(documentId)}/download`);
}

/** A 401 from any S1 call: the session expired or the user signed out. */
export function isSessionEnded(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

/** The login page to send an ended session to (back to `next` afterwards), or
 *  `null` when this browser does not know which org the user belongs to. */
export function signInAgainPath(next = "/"): string | null {
  const realm = lastRealm();
  return realm ? signInPath(realm, next) : null;
}

export function userFacingApiError(error: unknown): string {
  if (!(error instanceof Error)) return "Backend request failed.";
  if (error.message.includes(HALT_REASONS.unsupportedFormat)) return HALT_REASONS.unsupportedFormat;
  if (error.message.includes(HALT_REASONS.unreadable)) return HALT_REASONS.unreadable;
  return error.message;
}

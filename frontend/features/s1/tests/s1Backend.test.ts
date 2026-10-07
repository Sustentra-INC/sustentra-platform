/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../lib/api";
import { rememberRealm } from "../../auth/lastRealm";
import { mapBackendDocumentToEvidenceItem, inlineDocumentUrl } from "../adapters/evidenceAdapter";
import { encodeReviewCandidateToken } from "../adapters/fieldAdapter";
import {
  downloadUrl,
  getSignedInUser,
  isSessionEnded,
  listWorkspaceEvidence,
  processDocument,
  signInAgainPath,
  submitFieldReview,
  uploadDocument,
  userFacingApiError,
} from "../api/s1Backend";
import { MAX_UPLOAD_BYTES } from "../constants/uploads";
import type { ExtractedField } from "../types";

const fetchMock = vi.fn();

const candidate = {
  candidate_id: "candidate::EV-1::DOC-1::fuel_quantity",
  evidence_id: "EV-1",
  document_id: "DOC-1",
  field_name: "fuel_quantity",
  display_label: "Fuel quantity",
  normalized_value: 12,
  unit: "gal",
};

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const DOCUMENT = {
  document_id: "DOC-1",
  evidence_id: "EV-1",
  file_name: "bill.pdf",
  mime_type: "application/pdf",
  uploaded_by: "member@acme.test",
  uploaded_at: "2026-01-01T00:00:00Z",
  processing_status: "completed",
};

function routeFetch(input: RequestInfo | URL): Promise<Response> {
  const url = String(input);
  if (url.endsWith("/engagements/ENG-1/documents")) return Promise.resolve(json(200, { items: [DOCUMENT] }));
  if (url.endsWith("/latest-run")) return Promise.resolve(json(404, { detail: "Pipeline run not found." }));
  if (url.endsWith("/extraction-result/latest")) return Promise.resolve(json(404, { detail: "Not Found" }));
  if (url.endsWith("/reviews")) return Promise.resolve(json(200, []));
  return Promise.resolve(json(200, { ...DOCUMENT, email: "member@acme.test", role: "org_member" }));
}

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation(routeFetch);
  vi.stubGlobal("fetch", fetchMock);
  window.localStorage.clear();
  document.cookie = "sustentra_realm=; Path=/; Max-Age=0";
});
afterEach(() => vi.unstubAllGlobals());

function calls(): Array<{ url: string; init: RequestInit }> {
  return fetchMock.mock.calls.map(([url, init]) => ({ url: String(url), init: init as RequestInit }));
}

describe("S1 data seam on cookie auth (FE-007)", () => {
  it("sends every request same-origin to /api/v1 with the session cookie", async () => {
    await getSignedInUser();
    await listWorkspaceEvidence("ENG-1");
    await uploadDocument("ENG-1", new File(["pdf"], "bill.pdf", { type: "application/pdf" }));
    await processDocument("DOC-1");
    await submitFieldReview({
      field: { reviewToken: encodeReviewCandidateToken(candidate) } as unknown as ExtractedField,
      decision: "edited",
      reviewedValue: "12",
    });

    const sent = calls();
    expect(sent.length).toBeGreaterThanOrEqual(8);
    for (const { url, init } of sent) {
      expect(url.startsWith("/api/v1/")).toBe(true);
      expect(init.credentials).toBe("same-origin");
      expect(new Headers(init.headers).has("Authorization")).toBe(false);
    }
    expect(sent.map((c) => c.url)).toEqual(
      expect.arrayContaining([
        "/api/v1/auth/me",
        "/api/v1/engagements/ENG-1/documents",
        "/api/v1/pipeline/evidence/EV-1/latest-run",
        "/api/v1/documents/DOC-1/extraction-result/latest",
        "/api/v1/documents/DOC-1/reviews",
        "/api/v1/engagements/ENG-1/documents/upload",
        "/api/v1/documents/DOC-1/pipeline/process",
        "/api/v1/evidence/EV-1/fields/fuel_quantity/review",
      ])
    );
  });

  it("lets the API record the uploader and reviewer from the session", async () => {
    await uploadDocument("ENG-1", new File(["pdf"], "bill.pdf"));
    const upload = calls().find((c) => c.url.endsWith("/upload"))!;
    expect((upload.init.body as FormData).has("uploaded_by")).toBe(false);

    await submitFieldReview({
      field: { reviewToken: encodeReviewCandidateToken(candidate) } as unknown as ExtractedField,
      decision: "accepted",
    });
    const review = calls().find((c) => c.url.endsWith("/review"))!;
    expect(review.init.method).toBe("PUT");
    expect(JSON.parse(String(review.init.body))).not.toHaveProperty("reviewer_id");
  });

  it("treats a 404 on optional per-document data as missing, not an error", async () => {
    const workspace = await listWorkspaceEvidence("ENG-1");
    expect(workspace.evidence).toHaveLength(1);
    expect(workspace.fields).toEqual([]);
  });

  it("surfaces a 401 as an ended session", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json(401, { detail: "Not authenticated" })));
    const error = await listWorkspaceEvidence("ENG-1").catch((e: unknown) => e);
    expect(isSessionEnded(error)).toBe(true);
    expect(isSessionEnded(new ApiError(403, "Forbidden", null, null))).toBe(false);
    expect(isSessionEnded(new Error("network"))).toBe(false);
  });

  it("builds same-origin download and preview URLs", () => {
    expect(downloadUrl("DOC 1")).toBe("/api/v1/documents/DOC%201/download");
    expect(inlineDocumentUrl("DOC-1")).toBe("/api/v1/documents/DOC-1/preview");
    expect(mapBackendDocumentToEvidenceItem(DOCUMENT).downloadUrl).toBe("/api/v1/documents/DOC-1/download");
  });
});

describe("signInAgainPath", () => {
  it("is unknown until the user has signed in on this browser", () => {
    expect(signInAgainPath("/")).toBeNull();
  });

  it("sends org users to their org's login and back", () => {
    rememberRealm({ kind: "org", slug: "acme-foods" });
    expect(signInAgainPath("/?view=evidence")).toBe("/org/acme-foods/login?next=%2F%3Fview%3Devidence");
  });

  it("sends provider admins to the provider login", () => {
    rememberRealm({ kind: "provider" });
    expect(signInAgainPath()).toBe("/provider-admin/login?next=%2F");
  });
});

describe("upload size limit (INFRA-007)", () => {
  it("refuses a file over the limit without sending it", async () => {
    const big = new File(["x"], "big.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: MAX_UPLOAD_BYTES + 1 });
    const error = await uploadDocument("ENG-1", big).catch((e: unknown) => e);
    expect(userFacingApiError(error)).toBe("This file is larger than the 25 MB upload limit.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("uploads a file at the limit", async () => {
    const file = new File(["x"], "ok.pdf", { type: "application/pdf" });
    Object.defineProperty(file, "size", { value: MAX_UPLOAD_BYTES });
    await uploadDocument("ENG-1", file);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows the same message for a 413 from the API or the proxy", () => {
    const fromApi = new ApiError(413, "File is too large. The maximum upload size is 25 MB.", null, null);
    const fromProxy = new ApiError(413, "Request failed (413)", null, null);
    expect(userFacingApiError(fromApi)).toBe("This file is larger than the 25 MB upload limit.");
    expect(userFacingApiError(fromProxy)).toBe("This file is larger than the 25 MB upload limit.");
    expect(userFacingApiError(new ApiError(400, "Bad file", null, null))).toBe("Bad file");
  });
});

describe("halted documents (unreadable / unsupported)", () => {
  const failed = { ...DOCUMENT, processing_status: "failed" };

  it("shows the pipeline's halt reason on the evidence row", () => {
    const run = { status: "failed", errors: ["Parser stage returned failed status."],
      halt_reason: { code: "unreadable_document", message: "Unreadable document: ..." } };
    const item = mapBackendDocumentToEvidenceItem(failed, run);
    expect(item.processingState).toBe("blocked");
    expect(item.haltReason).toBe("File could not be read.");
  });

  it("maps an unsupported document type to the no-template reason", () => {
    const run = { status: "partial", candidate_count: 0, target_count: 0,
      halt_reason: { code: "unsupported_document", message: "Unsupported document type: ..." } };
    expect(mapBackendDocumentToEvidenceItem(DOCUMENT, run).haltReason).toBe(
      "No extraction template exists for this document type."
    );
  });

  it("falls back to the error text when there is no structured halt", () => {
    expect(mapBackendDocumentToEvidenceItem(failed, { status: "failed", errors: ["boom"] }).haltReason).toBe(
      "Processing failed. Retry available."
    );
  });

  it("turns the API's 422 halt message into the short reason", () => {
    expect(userFacingApiError(new ApiError(422, "Unreadable document: no text could be extracted ...", null, null)))
      .toBe("File could not be read.");
    expect(userFacingApiError(new ApiError(422, "Unsupported document type: it does not match ...", null, null)))
      .toBe("No extraction template exists for this document type.");
  });
});

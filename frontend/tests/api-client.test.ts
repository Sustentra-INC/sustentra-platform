import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, apiMaybe, apiPath } from "../lib/api";

const fetchMock = vi.fn();

function respond(status: number, body: unknown = {}) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("apiMaybe (FE-007)", () => {
  it("returns null on 404", async () => {
    fetchMock.mockResolvedValueOnce(respond(404, { detail: "Document not found." }));
    await expect(apiMaybe("/documents/DOC-1/reviews")).resolves.toBeNull();
  });

  it("returns the body on success", async () => {
    fetchMock.mockResolvedValueOnce(respond(200, [{ candidate_id: "c" }]));
    await expect(apiMaybe("/documents/DOC-1/reviews")).resolves.toEqual([{ candidate_id: "c" }]);
  });

  it.each([400, 401, 403, 500])("throws ApiError on %s", async (status) => {
    fetchMock.mockResolvedValueOnce(respond(status, { detail: "nope" }));
    const error = await apiMaybe("/documents/DOC-1/reviews").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(status);
    expect((error as ApiError).detail).toBe("nope");
  });
});

describe("api", () => {
  it("calls the same-origin /api/v1 path with the session cookie", async () => {
    fetchMock.mockResolvedValueOnce(respond(200, {}));
    await api("/auth/me");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/me");
    expect(init.credentials).toBe("same-origin");
  });

  it("builds same-origin URLs for links and iframes", () => {
    expect(apiPath("/documents/D/preview")).toBe("/api/v1/documents/D/preview");
  });
});

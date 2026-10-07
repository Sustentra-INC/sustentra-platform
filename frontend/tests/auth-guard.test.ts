import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock the Next server-only modules the guard depends on.
const redirectMock = vi.fn((path: string): never => {
  throw new Error(`REDIRECT:${path}`);
});
const cookieStore = { get: vi.fn() };

vi.mock("next/navigation", () => ({ redirect: (path: string) => redirectMock(path) }));
vi.mock("next/headers", () => ({ cookies: async () => cookieStore }));

import { requireSession, SessionCheckError } from "../lib/auth-guard";
import { SESSION_COOKIE } from "../lib/session-cookie";

function mockMe(role: string, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ id: "u1", email: "a@b.c", role }), { status })),
  );
}

beforeEach(() => {
  redirectMock.mockClear();
  cookieStore.get.mockReset();
  vi.unstubAllGlobals();
});

describe("requireSession server guard", () => {
  it("redirects to login when no session cookie is present", async () => {
    cookieStore.get.mockReturnValue(undefined);
    await expect(requireSession()).rejects.toThrow("REDIRECT:/provider-admin/login");
  });

  it("redirects to login when the API rejects the session (401)", async () => {
    cookieStore.get.mockReturnValue({ name: SESSION_COOKIE, value: "stale" });
    mockMe("org_admin", 401);
    await expect(requireSession({ loginPath: "/org/acme/login" })).rejects.toThrow(
      "REDIRECT:/org/acme/login",
    );
  });

  it("redirects an org_member away from an admin-only route", async () => {
    cookieStore.get.mockReturnValue({ name: SESSION_COOKIE, value: "sess" });
    mockMe("org_member");
    await expect(requireSession({ role: "org_admin", forbiddenPath: "/org/acme" })).rejects.toThrow(
      "REDIRECT:/org/acme",
    );
  });

  it("returns the user when the role is allowed", async () => {
    cookieStore.get.mockReturnValue({ name: SESSION_COOKIE, value: "sess" });
    mockMe("org_admin");
    const me = await requireSession({ role: ["org_admin", "provider_admin"] });
    expect(me.role).toBe("org_admin");
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("does not sign the user out when the API is rate limiting or failing (AUTH-007)", async () => {
    cookieStore.get.mockReturnValue({ name: SESSION_COOKIE, value: "sess" });
    for (const status of [429, 500, 503]) {
      mockMe("org_admin", status);
      await expect(requireSession({ loginPath: "/org/acme/login" })).rejects.toBeInstanceOf(SessionCheckError);
    }
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("does not sign the user out when the API is unreachable", async () => {
    cookieStore.get.mockReturnValue({ name: SESSION_COOKIE, value: "sess" });
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    await expect(requireSession()).rejects.toBeInstanceOf(SessionCheckError);
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("treats 403 from /me as signed out", async () => {
    cookieStore.get.mockReturnValue({ name: SESSION_COOKIE, value: "sess" });
    mockMe("org_admin", 403);
    await expect(requireSession({ loginPath: "/org/acme/login" })).rejects.toThrow("REDIRECT:/org/acme/login");
  });
});

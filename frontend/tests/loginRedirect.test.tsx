import { beforeEach, describe, expect, it, vi } from "vitest";

import { loginUrlFor, sameOriginPath } from "../lib/realm-cookie";
import { safeNext } from "../features/auth/lastRealm";

const mocks = vi.hoisted(() => ({ redirected: "" as string, realm: undefined as string | undefined }));
vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    mocks.redirected = url;
    throw new Error("NEXT_REDIRECT");
  },
}));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => (mocks.realm ? { value: mocks.realm } : undefined) }) }));
vi.mock("../lib/auth-guard", () => ({ getMe: async () => null }));
vi.mock("../features/s1/pages/S1WorkpaperApp", () => ({ S1WorkpaperApp: () => null }));

import HomePage from "../app/page";

const ORG = { kind: "org", slug: "acme" } as const;

beforeEach(() => {
  mocks.redirected = "";
  mocks.realm = undefined;
});

describe("the login redirect keeps the deep link", () => {
  it("passes the full path and query to the login page as next", () => {
    const next = "/?view=review&e=E1&doc=D%201";
    const url = new URL(loginUrlFor(ORG, next), "https://app.test");
    expect(url.pathname).toBe("/org/acme/login");
    expect(url.searchParams.get("next")).toBe(next);
    expect(new URL(loginUrlFor(null, next), "https://app.test").pathname).toBe("/sign-in");
  });

  it("the signed-out workpaper page sends the visitor to login with its query", async () => {
    mocks.realm = "org:acme";
    await expect(
      HomePage({ searchParams: Promise.resolve({ view: "review", doc: "D 1", e: "E1" }) }),
    ).rejects.toThrow("NEXT_REDIRECT");
    const url = new URL(mocks.redirected, "https://app.test");
    expect(url.pathname).toBe("/org/acme/login");
    expect(url.searchParams.get("next")).toBe("/?view=review&doc=D+1&e=E1");
    expect(safeNext(url.searchParams.get("next"))).toBe("/?view=review&doc=D+1&e=E1");
  });

  it("goes to / when there is no query", async () => {
    await expect(HomePage({ searchParams: Promise.resolve({}) })).rejects.toThrow("NEXT_REDIRECT");
    expect(new URL(mocks.redirected, "https://app.test").searchParams.get("next")).toBe("/");
  });
});

describe("next is a same-origin path only (no open redirect)", () => {
  const bad = [
    "https://evil.example",
    "http://evil.example/x",
    "//evil.example",
    "//evil.example/?view=x",
    "/\\evil.example",
    "\\\\evil.example",
    "javascript:alert(1)",
    "evil.example",
    "/ok\nSet-Cookie: x",
    "/ok\tx",
    "/ok\u007f",
    "",
    null,
    undefined,
  ];

  it("sameOriginPath and safeNext refuse everything that leaves the app", () => {
    for (const next of bad) {
      expect(sameOriginPath(next), String(next)).toBeNull();
      expect(safeNext(next), String(next)).toBeNull();
    }
    for (const ok of ["/", "/org/acme/tasks", "/?view=review&doc=1&e=2", "/a/b?x=https://other.example"]) {
      expect(sameOriginPath(ok)).toBe(ok);
      expect(safeNext(ok)).toBe(ok);
    }
  });

  it("loginUrlFor never builds a login link that returns somewhere else", () => {
    for (const next of bad) {
      const url = new URL(loginUrlFor(ORG, next as string), "https://app.test");
      expect(url.searchParams.get("next")).toBe("/");
    }
  });
});

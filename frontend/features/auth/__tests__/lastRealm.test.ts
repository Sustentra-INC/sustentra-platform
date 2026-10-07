/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { isOrgSlug, lastRealm, rememberRealm, safeNext, signInPath } from "../lastRealm";

beforeEach(() => {
  window.localStorage.clear();
  document.cookie = "sustentra_realm=; Path=/; Max-Age=0";
});
afterEach(() => vi.restoreAllMocks());

describe("lastRealm (FE-007)", () => {
  it("round-trips org and provider realms", () => {
    expect(lastRealm()).toBeNull();
    rememberRealm({ kind: "org", slug: "acme" });
    expect(lastRealm()).toEqual({ kind: "org", slug: "acme" });
    rememberRealm({ kind: "provider" });
    expect(lastRealm()).toEqual({ kind: "provider" });
  });

  it.each(["org:", "org:A", "org:../x", "org:ab", "something"])("ignores a tampered value %j", (value) => {
    window.localStorage.setItem("sustentra.lastRealm", value);
    expect(lastRealm()).toBeNull();
  });

  it("never throws when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(() => rememberRealm({ kind: "provider" })).not.toThrow();
    expect(lastRealm()).toEqual({ kind: "provider" }); // the cookie still works
    document.cookie = "sustentra_realm=; Path=/; Max-Age=0";
    expect(lastRealm()).toBeNull();
  });

  it("builds login paths with an encoded next", () => {
    expect(signInPath({ kind: "org", slug: "acme" }, "/?a=1&b=2")).toBe("/org/acme/login?next=%2F%3Fa%3D1%26b%3D2");
  });

  it("accepts only same-origin next paths", () => {
    expect(safeNext("/")).toBe("/");
    expect(safeNext("/org/acme?x=1")).toBe("/org/acme?x=1");
    for (const bad of [null, undefined, "", "//evil.example", "/\\evil.example", "https://evil.example", "evil", "/\nx"]) {
      expect(safeNext(bad)).toBeNull();
    }
  });

  it("validates slugs with the backend's rule", () => {
    expect(isOrgSlug("acme-foods")).toBe(true);
    expect(isOrgSlug("ab")).toBe(false);
    expect(isOrgSlug("Acme")).toBe(false);
  });

  it("prefers the realm cookie, which the edge middleware also reads (FE-006)", () => {
    rememberRealm({ kind: "org", slug: "acme" });
    expect(document.cookie).toContain("sustentra_realm=org%3Aacme");
    window.localStorage.setItem("sustentra.lastRealm", "provider");
    expect(lastRealm()).toEqual({ kind: "org", slug: "acme" });
  });

  it("falls back to storage when there is no cookie", () => {
    window.localStorage.setItem("sustentra.lastRealm", "org:beta-co");
    expect(lastRealm()).toEqual({ kind: "org", slug: "beta-co" });
  });
});

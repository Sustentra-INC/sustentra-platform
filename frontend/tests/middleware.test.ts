import { describe, it, expect } from "vitest";
import { NextRequest } from "next/server";

import { middleware, SESSION_COOKIE } from "../middleware";

function request(path: string, withSession = false): NextRequest {
  const req = new NextRequest(new URL(`https://app.sustentra.com${path}`));
  if (withSession) req.cookies.set(SESSION_COOKIE, "session-value");
  return req;
}

function location(path: string, withSession = false): URL | null {
  const res = middleware(request(path, withSession));
  const loc = res.headers.get("location");
  return loc ? new URL(loc) : null;
}

describe("middleware auth guard", () => {
  it("redirects to the provider login when signed out of /provider-admin/*", () => {
    const loc = location("/provider-admin/orgs");
    expect(loc?.pathname).toBe("/provider-admin/login");
    expect(loc?.searchParams.get("next")).toBe("/provider-admin/orgs");
  });

  it("redirects to the org login when signed out of /org/[slug]/*", () => {
    const loc = location("/org/acme/admin/users");
    expect(loc?.pathname).toBe("/org/acme/login");
    expect(loc?.searchParams.get("next")).toBe("/org/acme/admin/users");
  });

  it("leaves public org auth pages reachable without a session", () => {
    for (const page of ["/org/acme/login", "/org/acme/forgot-password", "/org/acme/reset-password"]) {
      expect(location(page)).toBeNull();
    }
  });

  it("leaves the provider login reachable without a session", () => {
    expect(location("/provider-admin/login")).toBeNull();
  });

  it("passes through when the session cookie is present", () => {
    expect(location("/org/acme/admin/users", true)).toBeNull();
    expect(location("/provider-admin/orgs", true)).toBeNull();
  });
});

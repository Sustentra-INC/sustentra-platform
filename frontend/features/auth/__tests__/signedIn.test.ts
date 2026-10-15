import { describe, expect, it } from "vitest";

import type { Me } from "../../../lib/auth-guard";
import { signedInRedirect } from "../signedIn";

const member: Me = { id: "u1", email: "m@acme.test", role: "org_member", org_slug: "acme" };
const provider: Me = { id: "p1", email: "p@sustentra.test", role: "provider_admin", org_slug: null };

describe("a login page visited while signed in", () => {
  it("sends a member of that organization on to the workpaper, or to a safe next", () => {
    expect(signedInRedirect(member, { kind: "org", slug: "acme" }, null)).toBe("/");
    expect(signedInRedirect(member, { kind: "org", slug: "acme" }, "/org/acme/admin/users")).toBe("/org/acme/admin/users");
    expect(signedInRedirect(member, { kind: "org", slug: "acme" }, "//evil.test")).toBe("/");
  });

  it("shows the login when signed out or signed in elsewhere", () => {
    expect(signedInRedirect(null, { kind: "org", slug: "acme" }, null)).toBeNull();
    expect(signedInRedirect(member, { kind: "org", slug: "other-co" }, null)).toBeNull();
    expect(signedInRedirect(provider, { kind: "org", slug: "acme" }, null)).toBeNull();
    expect(signedInRedirect(member, { kind: "provider" }, null)).toBeNull();
  });

  it("sends a provider admin on from the provider login", () => {
    expect(signedInRedirect(provider, { kind: "provider" }, null)).toBe("/provider-admin/orgs");
  });
});

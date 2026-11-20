/* @vitest-environment jsdom */
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../auth/api", () => ({ logout: vi.fn() }));

import { OrgHome } from "../OrgHome";
import type { Me } from "../orgApi";

const me = (role: Me["role"]): Me => ({ id: "u1", email: "ann@acme.test", role, first_name: "Ann", org_slug: "acme" });

afterEach(cleanup);

describe("Org home links", () => {
  it("links admins to the Tasks page, next to users and the audit log", () => {
    render(<OrgHome me={me("org_admin")} slug="acme" />);
    expect(screen.getByRole("link", { name: "Tasks" })).toHaveAttribute("href", "/org/acme/admin/tasks");
    expect(screen.getByRole("link", { name: "Manage users" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Audit log" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "My tasks" })).toHaveAttribute("href", "/org/acme/tasks");
  });

  it("gives members My tasks but not the admin Tasks page", () => {
    render(<OrgHome me={me("org_member")} slug="acme" />);
    expect(screen.getByRole("link", { name: "My tasks" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Tasks" })).toBeNull();
  });
});

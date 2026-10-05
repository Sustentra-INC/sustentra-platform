/* @vitest-environment jsdom */
import { describe, it, expect, vi, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

import { ApiError } from "../../../lib/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("../providerApi", async () => {
  const actual = await vi.importActual<typeof import("../providerApi")>("../providerApi");
  return {
    ...actual,
    getOrg: vi.fn(),
    suspendOrg: vi.fn(),
    activateOrg: vi.fn(),
    updateOrg: vi.fn(),
    createOrg: vi.fn(),
  };
});

import { getOrg, suspendOrg, createOrg } from "../providerApi";
import { OrgDetail } from "../OrgDetail";
import { CreateOrgForm } from "../CreateOrgForm";

const getOrgMock = getOrg as unknown as ReturnType<typeof vi.fn>;
const suspendMock = suspendOrg as unknown as ReturnType<typeof vi.fn>;
const createMock = createOrg as unknown as ReturnType<typeof vi.fn>;

const ORG = {
  id: "o1",
  name: "Acme Foods",
  slug: "acme",
  status: "active" as const,
  max_users: 10,
  user_count: 3,
};

beforeEach(() => vi.clearAllMocks());

describe("OrgDetail suspend confirmation", () => {
  it("requires the exact org name before suspend is enabled", async () => {
    getOrgMock.mockResolvedValue(ORG);
    suspendMock.mockResolvedValue(undefined);
    render(<OrgDetail orgId="o1" />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Acme Foods" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /^suspend$/i }));
    const dialog = screen.getByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: /^suspend$/i });
    expect(confirm).toBeDisabled();

    const input = within(dialog).getByLabelText(/type/i);
    fireEvent.change(input, { target: { value: "Wrong Name" } });
    expect(confirm).toBeDisabled();

    fireEvent.change(input, { target: { value: "Acme Foods" } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(suspendMock).toHaveBeenCalledWith("o1"));
  });
});

describe("CreateOrgForm", () => {
  it("surfaces the duplicate-slug error from the API", async () => {
    createMock.mockRejectedValueOnce(new ApiError(409, "slug exists", null, null));
    render(<CreateOrgForm />);
    fireEvent.change(screen.getByLabelText(/organization name/i), { target: { value: "Acme Foods" } });
    fireEvent.change(screen.getByLabelText("Slug"), { target: { value: "acme" } });
    fireEvent.click(screen.getByRole("button", { name: /create organization/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/slug is already taken/i));
  });

  it("blocks an invalid slug client-side before calling the API", () => {
    render(<CreateOrgForm />);
    fireEvent.change(screen.getByLabelText(/organization name/i), { target: { value: "Acme" } });
    fireEvent.change(screen.getByLabelText("Slug"), { target: { value: "no" } });
    fireEvent.click(screen.getByRole("button", { name: /create organization/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/3–63 lowercase/i);
    expect(createMock).not.toHaveBeenCalled();
  });
});

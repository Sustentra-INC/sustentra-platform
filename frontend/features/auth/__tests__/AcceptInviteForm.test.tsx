/* @vitest-environment jsdom */
import { describe, it, expect, vi, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const hoisted = vi.hoisted(() => ({ search: "token=invite-abc" }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(hoisted.search),
}));
vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, validateInvite: vi.fn(), acceptInvite: vi.fn() };
});

import { ApiError, validateInvite, acceptInvite } from "../api";
import { AcceptInviteForm } from "../AcceptInviteForm";

const validateMock = validateInvite as unknown as ReturnType<typeof vi.fn>;
const acceptMock = acceptInvite as unknown as ReturnType<typeof vi.fn>;

const INVITE = {
  org_name: "Acme Foods",
  org_slug: "acme",
  email: "sam@acme.com",
  first_name: "Sam",
  last_name: "Lee",
};

beforeEach(() => {
  vi.clearAllMocks();
  hoisted.search = "token=invite-abc";
});

describe("AcceptInviteForm", () => {
  it("shows the invalid state when the token is missing", () => {
    hoisted.search = "";
    render(<AcceptInviteForm />);
    expect(screen.getByText(/invalid or has expired/i)).toBeInTheDocument();
  });

  it("shows the invalid state when validation fails", async () => {
    validateMock.mockRejectedValueOnce(new Error("bad token"));
    render(<AcceptInviteForm />);
    await waitFor(() => expect(screen.getByText(/invalid or has expired/i)).toBeInTheDocument());
  });

  it("pre-fills the invitee details and submits a valid password", async () => {
    validateMock.mockResolvedValueOnce(INVITE);
    acceptMock.mockResolvedValueOnce(undefined);
    const onAccepted = vi.fn();
    render(<AcceptInviteForm onAccepted={onAccepted} />);

    await waitFor(() => expect(screen.getByText(/join acme foods/i)).toBeInTheDocument());
    expect(screen.getByDisplayValue("Sam Lee")).toBeInTheDocument();
    expect(screen.getByDisplayValue("sam@acme.com")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a-long-enough-password" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "a-long-enough-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: /activate account/i }));

    await waitFor(() => expect(acceptMock).toHaveBeenCalledWith("invite-abc", "a-long-enough-password"));
    await waitFor(() => expect(onAccepted).toHaveBeenCalledWith("/org/acme/login?status=ready"));
  });

  it("blocks mismatched passwords before calling the API", async () => {
    validateMock.mockResolvedValueOnce(INVITE);
    render(<AcceptInviteForm />);
    await waitFor(() => expect(screen.getByText(/join acme foods/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a-long-enough-password" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "different-password" } });
    fireEvent.click(screen.getByRole("button", { name: /activate account/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/do not match/i);
    expect(acceptMock).not.toHaveBeenCalled();
  });

  it("shows the server's password-policy message on 422", async () => {
    validateMock.mockResolvedValueOnce(INVITE);
    acceptMock.mockRejectedValueOnce(
      new ApiError(
        422,
        "Password does not meet the requirements",
        {
          detail: "Password does not meet the requirements",
          violations: ["Password is too common; choose something less predictable."],
        },
        null,
      ),
    );
    render(<AcceptInviteForm />);
    await waitFor(() => expect(screen.getByText(/join acme foods/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "password12345" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "password12345" } });
    fireEvent.click(screen.getByRole("button", { name: /activate account/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/too common/i));
  });
});

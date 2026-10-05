/* @vitest-environment jsdom */
import { describe, it, expect, vi, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent } from "@testing-library/react";

const hoisted = vi.hoisted(() => ({ search: "token=reset-abc" }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(hoisted.search),
}));
vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, resetPassword: vi.fn() };
});

import { resetPassword } from "../api";
import { ResetPasswordForm } from "../ResetPasswordForm";

const resetMock = resetPassword as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.clearAllMocks();
  hoisted.search = "token=reset-abc";
});

describe("ResetPasswordForm", () => {
  it("blocks mismatched passwords client-side", () => {
    render(<ResetPasswordForm realm={{ kind: "provider" }} />);
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "a-long-enough-password" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), {
      target: { value: "a-different-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: /update password/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/do not match/i);
    expect(resetMock).not.toHaveBeenCalled();
  });

  it("enforces the minimum length before calling the API", () => {
    render(<ResetPasswordForm realm={{ kind: "provider" }} />);
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "short" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "short" } });
    fireEvent.click(screen.getByRole("button", { name: /update password/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/at least 12 characters/i);
    expect(resetMock).not.toHaveBeenCalled();
  });

  it("shows an invalid-link state when there is no token", () => {
    hoisted.search = "";
    render(<ResetPasswordForm realm={{ kind: "provider" }} />);
    expect(screen.getByText(/invalid reset link/i)).toBeInTheDocument();
  });
});

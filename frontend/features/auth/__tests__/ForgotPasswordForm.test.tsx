/* @vitest-environment jsdom */
import { describe, it, expect, vi, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, requestPasswordReset: vi.fn() };
});

import { requestPasswordReset } from "../api";
import { ForgotPasswordForm } from "../ForgotPasswordForm";

const resetMock = requestPasswordReset as unknown as ReturnType<typeof vi.fn>;

async function submitEmail() {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "user@example.com" } });
  fireEvent.click(screen.getByRole("button", { name: /send reset link/i }));
  await waitFor(() => expect(screen.getByText(/if an account exists/i)).toBeInTheDocument());
}

beforeEach(() => vi.clearAllMocks());

describe("ForgotPasswordForm", () => {
  it("shows the neutral confirmation when the request succeeds", async () => {
    resetMock.mockResolvedValueOnce(undefined);
    render(<ForgotPasswordForm realm={{ kind: "provider" }} />);
    await submitEmail();
  });

  it("shows the SAME neutral confirmation when the request fails", async () => {
    resetMock.mockRejectedValueOnce(new Error("backend down"));
    render(<ForgotPasswordForm realm={{ kind: "org", slug: "acme" }} />);
    await submitEmail();
  });
});

/* @vitest-environment jsdom */
import { describe, it, expect, vi, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { ApiError } from "../../../lib/api";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, login: vi.fn(), verifyOtp: vi.fn(), resendOtp: vi.fn() };
});

import { login, verifyOtp } from "../api";
import { LoginFlow } from "../LoginFlow";

const loginMock = login as unknown as ReturnType<typeof vi.fn>;
const verifyMock = verifyOtp as unknown as ReturnType<typeof vi.fn>;

function fillCredentials() {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "user@example.com" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a-good-password" } });
}

beforeEach(() => vi.clearAllMocks());

describe("LoginFlow", () => {
  it("validates an empty submit without calling the API", () => {
    render(<LoginFlow realm={{ kind: "provider" }} />);
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(screen.getByRole("alert")).toHaveTextContent(/enter your email and password/i);
    expect(loginMock).not.toHaveBeenCalled();
  });

  it("renders a generic error for a 401", async () => {
    loginMock.mockRejectedValueOnce(new ApiError(401, "unauthorized", null, null));
    render(<LoginFlow realm={{ kind: "provider" }} />);
    fillCredentials();
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/invalid email or password/i));
  });

  it("shows a lockout message with minutes from Retry-After on a 429", async () => {
    loginMock.mockRejectedValueOnce(new ApiError(429, "locked", null, 120));
    render(<LoginFlow realm={{ kind: "provider" }} />);
    fillCredentials();
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/try again in 2 minutes/i));
  });

  it("auto-submits the OTP on the 6th digit and navigates home", async () => {
    loginMock.mockResolvedValueOnce({ challenge_id: "ch_1" });
    verifyMock.mockResolvedValueOnce(undefined);
    const onAuthenticated = vi.fn();
    render(<LoginFlow realm={{ kind: "org", slug: "acme" }} onAuthenticated={onAuthenticated} />);
    fillCredentials();
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    const otp = await screen.findByLabelText(/6-digit code/i);
    expect(verifyMock).not.toHaveBeenCalled();
    fireEvent.change(otp, { target: { value: "123456" } });

    await waitFor(() => expect(verifyMock).toHaveBeenCalledWith("ch_1", "123456"));
    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith("/org/acme"));
  });
});

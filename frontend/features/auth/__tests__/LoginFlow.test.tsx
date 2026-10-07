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

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  document.cookie = "sustentra_realm=; Path=/; Max-Age=0";
});

async function signInThroughOtp(props: Partial<Parameters<typeof LoginFlow>[0]> = {}) {
  loginMock.mockResolvedValueOnce({ challenge_id: "ch_1" });
  verifyMock.mockResolvedValueOnce(undefined);
  const onAuthenticated = vi.fn();
  render(<LoginFlow realm={{ kind: "org", slug: "acme" }} onAuthenticated={onAuthenticated} {...props} />);
  fillCredentials();
  fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
  fireEvent.change(await screen.findByLabelText(/6-digit code/i), { target: { value: "123456" } });
  await waitFor(() => expect(onAuthenticated).toHaveBeenCalled());
  return onAuthenticated.mock.calls[0][0] as string;
}

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
    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith("/"));
  });

  it("returns to a same-origin ?next= path after login (FE-007)", async () => {
    expect(await signInThroughOtp({ next: "/?view=evidence" })).toBe("/?view=evidence");
  });

  it.each(["//evil.example", "https://evil.example/", "/\\evil.example", "javascript:alert(1)"])(
    "ignores an off-site ?next= (%s) and goes home",
    async (next) => {
      expect(await signInThroughOtp({ next })).toBe("/");
    }
  );

  it("remembers the org it signed in to, for the workpaper's session-ended redirect", async () => {
    await signInThroughOtp();
    expect(window.localStorage.getItem("sustentra.lastRealm")).toBe("org:acme");
    expect(document.cookie).toContain("sustentra_realm=org%3Aacme");
  });

  it("sends provider admins to their org list (FE-006)", async () => {
    expect(await signInThroughOtp({ realm: { kind: "provider" } })).toBe("/provider-admin/orgs");
  });
});

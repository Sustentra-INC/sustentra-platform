/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { SessionEndedPanel } from "../components/SessionEndedPanel";

describe("SessionEndedPanel (FE-007)", () => {
  it("sends the user to their org's login and back to the workpaper", () => {
    const onNavigate = vi.fn();
    render(<SessionEndedPanel next="/" onNavigate={onNavigate} />);
    fireEvent.change(screen.getByLabelText("Organization"), { target: { value: " Acme-Foods " } });
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(onNavigate).toHaveBeenCalledWith("/org/acme-foods/login?next=%2F");
  });

  it("rejects an invalid organization name", () => {
    const onNavigate = vi.fn();
    render(<SessionEndedPanel onNavigate={onNavigate} />);
    fireEvent.change(screen.getByLabelText("Organization"), { target: { value: "../evil" } });
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
    expect(onNavigate).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/sign-in name/i);
  });

  it("links provider admins to their login", () => {
    render(<SessionEndedPanel next="/" onNavigate={vi.fn()} />);
    expect(screen.getByRole("link", { name: /provider admin/i })).toHaveAttribute("href", "/provider-admin/login?next=%2F");
  });
});

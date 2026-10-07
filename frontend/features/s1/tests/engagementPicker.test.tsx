/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { EngagementPicker } from "../components/EngagementPicker";

const LIST = [
  { id: "e1", name: "FY2024", clientName: "Acme Foods" },
  { id: "e2", name: "FY2025", clientName: null },
];

describe("EngagementPicker (S1-BE-002)", () => {
  it("asks for a first engagement when the org has none", async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    render(<EngagementPicker engagements={[]} selectedId="" onSelect={vi.fn()} onCreate={onCreate} />);
    expect(screen.getByText(/create your first engagement/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/give the engagement a name/i);
    expect(onCreate).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/new engagement name/i), { target: { value: "FY2024" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(onCreate).toHaveBeenCalledWith("FY2024"));
  });

  it("lists the org's engagements and switches between them", () => {
    const onSelect = vi.fn();
    render(<EngagementPicker engagements={LIST} selectedId="e1" onSelect={onSelect} onCreate={vi.fn()} />);
    const select = screen.getByLabelText("Working on");
    expect(select).toHaveValue("e1");
    expect(screen.getByRole("option", { name: "FY2024 — Acme Foods" })).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "e2" } });
    expect(onSelect).toHaveBeenCalledWith("e2");
  });

  it("shows why a new engagement could not be created", async () => {
    const onCreate = vi.fn().mockRejectedValue(new Error("Your role can view engagements but not create them."));
    render(<EngagementPicker engagements={LIST} selectedId="e1" onSelect={vi.fn()} onCreate={onCreate} />);
    fireEvent.click(screen.getByRole("button", { name: /new engagement/i }));
    fireEvent.change(screen.getByLabelText(/new engagement name/i), { target: { value: "FY2026" } });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/not create them/));
  });

  it("reports the save state", () => {
    const { rerender } = render(
      <EngagementPicker engagements={LIST} selectedId="e1" onSelect={vi.fn()} onCreate={vi.fn()} saveState="saving" />
    );
    expect(screen.getByRole("status")).toHaveTextContent("Saving…");
    rerender(
      <EngagementPicker engagements={LIST} selectedId="e1" onSelect={vi.fn()} onCreate={vi.fn()}
        saveState="error" message="Changes not saved." />
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Changes not saved.");
  });
});

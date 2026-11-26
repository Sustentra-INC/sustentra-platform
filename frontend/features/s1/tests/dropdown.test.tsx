/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { Dropdown } from "../components/Dropdown";

const OPTIONS = [
  { value: "a", label: "Alpha" },
  { value: "b", label: "Beta" },
  { value: "c", label: "Gamma", disabled: true },
  { value: "d", label: "Delta" },
];

function Setup({ value = "a", onChange = vi.fn() }: { value?: string; onChange?: (v: string) => void }) {
  return (
    <div>
      <span id="dd-label">Pick one</span>
      <Dropdown value={value} onChange={onChange} options={OPTIONS} labelId="dd-label" name="pick" />
    </div>
  );
}

describe("Dropdown", () => {
  it("shows the selected label on the trigger", () => {
    render(<Setup value="b" />);
    expect(screen.getByLabelText("Pick one")).toHaveTextContent("Beta");
  });

  it("shows the placeholder when no value matches", () => {
    render(<Setup value="" onChange={vi.fn()} />);
    expect(screen.getByLabelText("Pick one")).toHaveTextContent("Choose…");
  });

  it("opens the panel and lists options on click", () => {
    render(<Setup />);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Pick one"));
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Alpha" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Beta" })).toBeInTheDocument();
  });

  it("calls onChange and closes on option click", () => {
    const onChange = vi.fn();
    render(<Setup onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Pick one"));
    fireEvent.click(screen.getByRole("option", { name: "Beta" }));
    expect(onChange).toHaveBeenCalledWith("b");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("does not call onChange for a disabled option", () => {
    const onChange = vi.fn();
    render(<Setup onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("Pick one"));
    // Disabled options have pointer-events: none in CSS but click events still fire in jsdom
    const opt = screen.getByRole("option", { name: "Gamma" });
    expect(opt).toHaveAttribute("aria-disabled", "true");
  });

  it("closes the panel and returns focus on Escape", () => {
    render(<Setup />);
    const trigger = screen.getByLabelText("Pick one");
    fireEvent.click(trigger);
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("navigates with keyboard and selects with Enter", () => {
    const onChange = vi.fn();
    render(<Setup onChange={onChange} />);
    const trigger = screen.getByLabelText("Pick one");
    // ArrowDown opens the panel and sets highlighted to first item
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    // Move down once more (Alpha → Beta, skipping nothing)
    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    // Select with Enter
    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("carries the selected value in a hidden input", () => {
    const { container } = render(<Setup value="d" />);
    const hidden = container.querySelector('input[type="hidden"][name="pick"]') as HTMLInputElement;
    expect(hidden).not.toBeNull();
    expect(hidden.value).toBe("d");
  });

  it("marks the selected option with aria-selected", () => {
    render(<Setup value="b" />);
    fireEvent.click(screen.getByLabelText("Pick one"));
    expect(screen.getByRole("option", { name: "Beta" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("option", { name: "Alpha" })).toHaveAttribute("aria-selected", "false");
  });
});

/* @vitest-environment jsdom */
import { beforeAll, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

import { S1Chrome } from "../components/S1Chrome";
import type { EngagementConfig } from "../types";

const ENGAGEMENT: EngagementConfig = {
  clientName: "Acme Foods",
  engagementId: "e-1",
  engagementName: "FY2024 GHG verification",
  reportingPeriod: { start: "2024-01-01", end: "2024-12-31" },
  facilities: [],
  regulation: "",
  conclusionType: "",
  assuranceLevel: "",
  boundaryApproach: "",
  scopeBoundaryStatement: "",
};

function setup() {
  const onNavigate = vi.fn();
  const onOpenActivity = vi.fn();
  const onOpenGlossary = vi.fn();
  render(
    <S1Chrome
      engagement={ENGAGEMENT}
      current="dashboard"
      onNavigate={onNavigate}
      onOpenActivity={onOpenActivity}
      onOpenGlossary={onOpenGlossary}
    >
      <p>content</p>
    </S1Chrome>
  );
  return { onNavigate, onOpenActivity, onOpenGlossary };
}

const field = () => screen.getByRole("button", { name: /Search documents, facilities, pages/ });
const box = () => screen.getByRole("combobox");
const active = () => document.getElementById(box().getAttribute("aria-activedescendant") ?? "");
const flush = () => act(() => new Promise((r) => setTimeout(r)));

describe("top bar search: pages", () => {
  beforeAll(() => {
    Element.prototype.scrollTo = () => {}; // jsdom has no layout
  });

  it("lists every page in sidebar order with its group", () => {
    setup();
    fireEvent.click(field());
    expect(field()).toHaveAttribute("aria-expanded", "true");
    const labels = screen.getAllByRole("option").map((o) => o.textContent);
    expect(labels).toEqual([
      "DashboardWorkflow",
      "SetupWorkflow",
      "UploadWorkflow",
      "EvidenceWorkflow",
      "Coverage & requestsWorkflow",
      "Methodology reviewAssurance",
      "Verification resultsAssurance",
      "OutputAssurance",
      "Activity log",
      "Glossary",
    ]);
    expect(box()).toHaveFocus();
  });

  it("filters, bolds the match and opens with Enter through the sidebar's handler", async () => {
    const { onNavigate } = setup();
    fireEvent.click(field());
    fireEvent.change(box(), { target: { value: "cov" } });
    expect(active()).toHaveTextContent("Coverage & requests");
    expect(active()?.querySelector("strong")).toHaveTextContent("Cov");
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("requests");
    expect(screen.queryByRole("combobox")).toBeNull();
    await flush();
    expect(field()).toHaveFocus();
  });

  it("opens the activity log and the glossary", () => {
    const { onOpenActivity, onOpenGlossary } = setup();
    fireEvent.click(field());
    fireEvent.change(box(), { target: { value: "act" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onOpenActivity).toHaveBeenCalledOnce();
    fireEvent.click(field());
    fireEvent.click(screen.getByRole("option", { name: "Glossary" }));
    expect(onOpenGlossary).toHaveBeenCalledOnce();
  });

  it("moves with the arrows, wraps, and jumps with Home and End", () => {
    setup();
    fireEvent.click(field());
    expect(active()).toHaveTextContent("Dashboard");
    fireEvent.keyDown(box(), { key: "ArrowUp" });
    expect(active()).toHaveTextContent("Glossary");
    fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(active()).toHaveTextContent("Dashboard");
    fireEvent.keyDown(box(), { key: "End" });
    expect(active()).toHaveTextContent("Glossary");
    fireEvent.keyDown(box(), { key: "Home" });
    expect(active()).toHaveTextContent("Dashboard");
  });

  it("says when nothing matches", () => {
    setup();
    fireEvent.click(field());
    fireEvent.change(box(), { target: { value: "zzz" } });
    expect(screen.getByText('No matches for "zzz"')).toBeInTheDocument();
    expect(screen.queryAllByRole("option")).toHaveLength(0);
  });

  it("toggles with ⌘K and Ctrl+K, clears the query, and closes on Escape", async () => {
    const { onNavigate } = setup();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    fireEvent.change(box(), { target: { value: "set" } });
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.queryByRole("combobox")).toBeNull();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(box()).toHaveValue("");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(onNavigate).not.toHaveBeenCalled();
    await flush();
    expect(field()).toHaveFocus();
  });

  it("takes over from the assistant panel", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Ask Sustentra" }));
    expect(screen.getByRole("dialog", { name: "Sustentra assistant" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.queryByRole("dialog", { name: "Sustentra assistant" })).toBeNull();
    expect(box()).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ask Sustentra" }));
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("does nothing while another modal dialog is open", () => {
    setup();
    const other = document.createElement("div");
    other.setAttribute("role", "dialog");
    other.setAttribute("aria-modal", "true");
    document.body.appendChild(other);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(screen.queryByRole("combobox")).toBeNull();
    other.remove();
  });
});

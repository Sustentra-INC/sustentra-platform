/* @vitest-environment jsdom */
import { beforeAll, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

import { S1Chrome } from "../components/S1Chrome";
import type { EngagementConfig, EvidenceItem } from "../types";

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

const FACILITIES = [
  { facilityId: "kent", name: "Kent Cannery" },
  { facilityId: "tual", name: "Tualatin Plant" },
];

function evidence(n: number): EvidenceItem[] {
  return Array.from({ length: n }, (_, i) => ({
    documentId: `d${i}`,
    filename: `kent_bill_${String(i).padStart(2, "0")}.pdf`,
    disposition: "active",
    detectedType: "Electricity bill",
    facilityState: "resolved",
    facilityId: "kent",
    facilityName: "Kent Cannery",
    periodStart: "2025-09-01",
    periodEnd: "2025-09-30",
  })) as EvidenceItem[];
}

function setup(docs: EvidenceItem[] = evidence(8)) {
  const onNavigate = vi.fn();
  const onOpenActivity = vi.fn();
  const onOpenGlossary = vi.fn();
  const onOpenDocument = vi.fn();
  render(
    <S1Chrome
      engagement={ENGAGEMENT}
      search={{ evidence: docs, facilities: FACILITIES, onOpenDocument }}
      current="dashboard"
      onNavigate={onNavigate}
      onOpenActivity={onOpenActivity}
      onOpenGlossary={onOpenGlossary}
    >
      <p>content</p>
    </S1Chrome>
  );
  return { onNavigate, onOpenActivity, onOpenGlossary, onOpenDocument };
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

  it("shows no documents or facilities until something is typed", () => {
    setup();
    fireEvent.click(field());
    expect(screen.queryByRole("group", { name: /Documents/ })).toBeNull();
    expect(screen.queryByRole("group", { name: "Facilities" })).toBeNull();
  });

  it("groups documents and facilities, caps documents at 6 and shows all on request", () => {
    setup();
    fireEvent.click(field());
    fireEvent.change(box(), { target: { value: "kent" } });
    const docs = screen.getByRole("group", { name: "Documents 8" });
    expect(docs.querySelectorAll('[role="option"]')).toHaveLength(7);
    expect(screen.getByRole("option", { name: "Show all 8 documents" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Facilities" })).toHaveTextContent("Kent Cannery8 documents");
    expect(screen.getByRole("option", { name: /kent_bill_00\.pdf/ })).toHaveTextContent(
      "kent_bill_00.pdfElectricity bill · Kent Cannery · September 2025"
    );
    for (let i = 0; i < 6; i += 1) fireEvent.keyDown(box(), { key: "ArrowDown" });
    expect(active()).toHaveTextContent("Show all 8 documents");
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(docs.querySelectorAll('[role="option"]')).toHaveLength(8);
    expect(active()).toHaveTextContent("kent_bill_06.pdf");
  });

  it("opens a document through the app's handler and closes", () => {
    const { onOpenDocument } = setup();
    fireEvent.click(field());
    fireEvent.change(box(), { target: { value: "bill 03" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(onOpenDocument).toHaveBeenCalledWith("d3");
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("filters to a facility with a removable chip; Escape lifts the chip, then closes", () => {
    setup();
    fireEvent.click(field());
    fireEvent.change(box(), { target: { value: "tualatin" } });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(box()).toHaveValue("");
    expect(screen.getByText("No documents for Tualatin Plant")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove Tualatin Plant" }));
    fireEvent.change(box(), { target: { value: "kent cannery" } });
    fireEvent.click(screen.getByRole("option", { name: /^Kent Cannery\d/ }));
    expect(screen.getByRole("group", { name: "Documents 8" }).querySelectorAll('[role="option"]')).toHaveLength(8);
    fireEvent.keyDown(box(), { key: "Backspace" });
    expect(screen.queryByRole("button", { name: "Remove Kent Cannery" })).toBeNull();
    fireEvent.change(box(), { target: { value: "kent cannery" } });
    fireEvent.keyDown(box(), { key: "End" });
    fireEvent.keyDown(box(), { key: "Enter" });
    expect(screen.getByRole("button", { name: "Remove Kent Cannery" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Remove Kent Cannery" })).toBeNull();
    expect(box()).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("works with nothing loaded yet", () => {
    setup([]);
    fireEvent.click(field());
    fireEvent.change(box(), { target: { value: "kent" } });
    expect(screen.queryByRole("group", { name: /Documents/ })).toBeNull();
    expect(screen.getByRole("group", { name: "Facilities" })).toHaveTextContent("0 documents");
  });
});

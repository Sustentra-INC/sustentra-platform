/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ byPath: {} as Record<string, unknown>, calls: [] as { path: string; options?: { method?: string; body?: unknown } }[] }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn((path: string, options?: { method?: string; body?: unknown }) => {
    mocks.calls.push({ path, options });
    const value = mocks.byPath[path];
    return value instanceof Error ? Promise.reject(value) : Promise.resolve(value ?? {});
  }),
}));

import { ApiError } from "../../../lib/api";
import { saveDocumentPlacement, withPlacement, type CalculationLine, type EvidenceTree as TreeData, type LineSchedule, type TreeDocRow } from "../api/evidenceTree";
import { engagementFromBackend, engagementToBackend } from "../api/engagements";
import { EvidenceTree, type EvidenceTreeProps } from "../components/EvidenceTree";
import { EvidenceWorkspace } from "../components/EvidenceWorkspace";
import { SupportingSchedule } from "../components/SupportingSchedule";
import { resultsViewForLine, scheduleViewForLine } from "../pages/lineLinks";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import type { EngagementConfig } from "../types";

const ENG = "eng-1";
const TREE_PATH = `/engagements/${ENG}/evidence-tree`;

const doc = (id: string, over: Partial<TreeDocRow> = {}): TreeDocRow => ({
  document_id: id,
  file_name: `${id}.pdf`,
  period_start: "2025-01-01",
  period_end: "2025-01-31",
  facility_id: "FAC-KC01",
  facility_name: "Kent",
  processing_status: "completed",
  detected_type: "Natural gas bill",
  also_in: [],
  value_family: "stationary",
  values: 4,
  accepted: 2,
  flags: [],
  ...over,
});

const counts = (documents: number, accepted: number, values: number) => ({
  documents,
  values,
  accepted,
  to_review: values - accepted,
  issues: 0,
  pct_accepted: values ? Math.floor((accepted / values) * 100) : 0,
});

const line = (key: string, label: string, over: Partial<CalculationLine> = {}): CalculationLine => ({
  key,
  scope: "s1",
  category: "stationary",
  level2: "natural-gas",
  level2_label: "Natural gas",
  anchor_kind: "facility",
  anchor_id: key.split(":")[3].toUpperCase(),
  label,
  facility_id: null,
  created_by_user: false,
  ...over,
});

const KENT = line("s1:stationary:natural-gas:fac-kc01", "Kent", { family: "stationary" });
const PLANT = line("s1:stationary:natural-gas:fac-pl02", "Plant 2", { created_by_user: true, family: "stationary", created_by_name: "Jane Park", created_at: "2025-11-04T12:00:00Z" });
const ELEC = line("s2:purchased_energy:electricity:fac-kc01", "Kent", { scope: "s2", category: "purchased_energy", level2: "electricity", level2_label: "Electricity", family: "electricity" });

const TREE: TreeData = {
  blocks: {
    summary_counts: counts(1, 0, 0),
    unassigned_counts: counts(1, 0, 0),
    summary: [doc("workbook", { file_name: "GHG workbook.xlsx", detected_type: "Inventory workbook", values: 0, accepted: 0 })],
    unassigned: [doc("scan", { file_name: "scan-001.pdf", processing_status: "failed", detected_type: null, facility_id: null, facility_name: null, values: 0, accepted: 0 })],
    supporting: {
      scopes: [
        {
          scope: "s1",
          label: "Scope 1",
          counts: counts(3, 4, 12),
          categories: [
            {
              category: "stationary",
              label: "Stationary combustion",
              counts: counts(3, 4, 12),
              level2s: [
                {
                  level2: "natural-gas",
                  label: "Natural gas",
                  counts: counts(3, 4, 12),
                  lines: [
                    { line: KENT, counts: counts(2, 3, 8), documents: [doc("jan", { also_in: [ELEC.key] }), doc("feb", { facility_id: "FAC-PL02", facility_name: "Plant 2" })] },
                    { line: PLANT, counts: counts(1, 1, 4), documents: [doc("mar", { facility_id: "FAC-PL02", facility_name: "Plant 2" })] },
                  ],
                },
              ],
            },
          ],
        },
        {
          scope: "s2",
          label: "Scope 2",
          counts: counts(1, 0, 4),
          categories: [
            {
              category: "purchased_energy",
              label: "Purchased energy",
              counts: counts(1, 0, 4),
              level2s: [{ level2: "electricity", label: "Electricity", counts: counts(1, 0, 4), lines: [{ line: ELEC, counts: counts(1, 0, 4), documents: [doc("jan", { also_in: [KENT.key] })] }] }],
            },
          ],
        },
      ],
      unassigned: [],
    },
  },
  facilities: [
    { facility_id: "FAC-KC01", name: "Kent" },
    { facility_id: "FAC-PL02", name: "Plant 2" },
  ],
  vehicle_groups: [{ anchor_id: "vg-fleet-a", label: "Fleet A (diesel)", fuel: "Diesel" }],
  lines: [KENT, PLANT, ELEC],
  set_aside: [{ document_id: "old", file_name: "old-bill.pdf", reason: "Replaced by a newer bill" }],
};

const ENGAGEMENT: EngagementConfig = {
  ...engagementConfig,
  engagementId: ENG,
  facilities: [
    { facilityId: "FAC-KC01", name: "Kent" },
    { facilityId: "FAC-PL02", name: "Plant 2" },
    { facilityId: "FAC-NW03", name: "North works" },
  ],
  evidenceLines: [{ key: PLANT.key, scope: "s1", category: "stationary", level2_label: "Natural gas", anchor_kind: "facility", anchor_id: "FAC-PL02", label: "Plant 2" }],
};

function Harness(over: Partial<EvidenceTreeProps> = {}) {
  const [open, setOpen] = useState<string[] | null>(null);
  return (
    <EvidenceTree
      engagement={ENGAGEMENT}
      reloadKey="a"
      facilityId={null}
      onFacilityChange={vi.fn()}
      openIds={open}
      onOpenIdsChange={setOpen}
      onOpenExtraction={vi.fn()}
      onOpenSchedule={vi.fn()}
      onMovePlacement={vi.fn().mockResolvedValue(undefined)}
      onSaveLines={vi.fn().mockResolvedValue(undefined)}
      onAudit={vi.fn()}
      writesEnabled
      {...over}
    />
  );
}

beforeEach(() => {
  mocks.byPath = { [TREE_PATH]: TREE };
  mocks.calls = [];
});

const expandAll = async () => {
  await screen.findByText("Summary documents and workbook");
  fireEvent.click(screen.getByRole("button", { name: "Expand all" }));
};

describe("the Evidence tree", () => {
  it("shows the three blocks, the scopes, document counts and % accepted", async () => {
    render(<Harness />);
    expect(await screen.findByText("Summary documents and workbook")).toBeInTheDocument();
    expect(screen.getByText("Unassigned documents")).toBeInTheDocument();
    expect(screen.getByText("System could not identify these")).toBeInTheDocument();
    expect(screen.getByText("Supporting evidence")).toBeInTheDocument();
    expect(screen.getByText("Scope 1")).toBeInTheDocument();
    expect(screen.getByText("Scope 2")).toBeInTheDocument();
    await expandAll();
    const category = screen.getByText("Stationary combustion").closest("section") as HTMLElement;
    const head = category.querySelector(".s1-et-head") as HTMLElement;
    expect(within(head).getByText("3 documents")).toBeInTheDocument();
    expect(within(head).getByText("33% accepted")).toBeInTheDocument();
    expect(screen.getAllByText("1 document").length).toBeGreaterThan(0);
    expect(screen.getByText("Added by J. Park \u00b7 Nov 4")).toBeInTheDocument();
    expect(screen.getByText("Also in Scope 2 › Purchased energy › Electricity › Kent")).toBeInTheDocument();
    expect(screen.getByText("Set aside")).toBeInTheDocument();
  });

  it("draws no bar segment for a zero count, so an empty row shows no coloured stubs", async () => {
    render(<Harness />);
    await screen.findByText("Summary documents and workbook");
    const bars = Array.from(document.querySelectorAll(".s1-et-bar-track"));
    expect(bars.length).toBeGreaterThan(0);
    for (const bar of bars) {
      for (const seg of Array.from(bar.querySelectorAll(".s1-ws-gr__seg")) as HTMLElement[]) {
        expect(Number(seg.style.flexGrow)).toBeGreaterThan(0);
      }
    }
    // Purchased energy has 0 accepted values and no issues: only its to-review segment may exist.
    const energy = screen.getByText("Purchased energy").closest("section") as HTMLElement;
    expect(energy.querySelector(".s1-et-bar-track .s1-ws-gr__seg--open")).not.toBeNull();
    expect(energy.querySelector(".s1-et-bar-track .s1-ws-gr__seg--resolved")).toBeNull();
    expect(energy.querySelector(".s1-et-bar-track .s1-ws-gr__seg--blocking")).toBeNull();
  });

  it("opens a document in the extraction review", async () => {
    const onOpenExtraction = vi.fn();
    render(<Harness onOpenExtraction={onOpenExtraction} />);
    await expandAll();
    fireEvent.click(screen.getByRole("button", { name: "scan-001.pdf" }));
    expect(onOpenExtraction).toHaveBeenCalledWith("scan");
  });

  it("opens a line's supporting schedule from its icon", async () => {
    const onOpenSchedule = vi.fn();
    render(<Harness onOpenSchedule={onOpenSchedule} />);
    await expandAll();
    fireEvent.click(screen.getByRole("button", { name: "Open supporting schedule for Natural gas · Kent" }));
    expect(onOpenSchedule).toHaveBeenCalledWith(KENT.key);
  });

  it("asks before a move that changes a calculation, then saves it once", async () => {
    const onMovePlacement = vi.fn().mockResolvedValue(undefined);
    const onAudit = vi.fn();
    render(<Harness onMovePlacement={onMovePlacement} onAudit={onAudit} />);
    await expandAll();
    const row = screen.getByRole("button", { name: "feb.pdf" }).closest(".s1-et-doc") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Actions for feb.pdf" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Move to…" }));
    const dialog = screen.getByRole("dialog", { name: "Move to…" });
    fireEvent.change(within(dialog).getByLabelText("Move to"), { target: { value: PLANT.key } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Move" }));
    expect(screen.getByRole("alert")).toHaveTextContent("4 values move from Natural gas · Kent to Natural gas · Plant 2. Both lines' calculations change.");
    expect(onMovePlacement).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm move" }));
    await waitFor(() => expect(onMovePlacement).toHaveBeenCalledWith("feb", { from: KENT.key, to: PLANT.key }));
    expect(onAudit).toHaveBeenCalledWith(expect.objectContaining({ action: "move_placement", documentId: "feb" }));
  });

  it("moves between blocks without asking", async () => {
    const onMovePlacement = vi.fn().mockResolvedValue(undefined);
    render(<Harness onMovePlacement={onMovePlacement} />);
    await expandAll();
    fireEvent.click(screen.getByRole("button", { name: "Actions for scan-001.pdf" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Move to…" }));
    const dialog = screen.getByRole("dialog", { name: "Move to…" });
    fireEvent.change(within(dialog).getByLabelText("Move to"), { target: { value: "supporting:unassigned" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Move" }));
    await waitFor(() => expect(onMovePlacement).toHaveBeenCalledWith("scan", { from: "block:unassigned", to: "supporting:unassigned" }));
  });

  it("adds a calculation line to the engagement's evidenceLines", async () => {
    const onSaveLines = vi.fn().mockResolvedValue(undefined);
    render(<Harness onSaveLines={onSaveLines} />);
    await expandAll();
    fireEvent.click(screen.getByRole("button", { name: "New calculation line in Natural gas" }));
    const dialog = screen.getByRole("dialog", { name: "New calculation line in Natural gas" });
    fireEvent.change(within(dialog).getByLabelText("Facility"), { target: { value: "FAC-NW03" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add line" }));
    await waitFor(() =>
      expect(onSaveLines).toHaveBeenCalledWith([
        ...ENGAGEMENT.evidenceLines!,
        { scope: "s1", category: "stationary", level2_label: "Natural gas", anchor_kind: "facility", anchor_id: "FAC-NW03", label: "North works" },
      ])
    );
  });

  it("shows the server's message when a line is refused", async () => {
    const onSaveLines = vi.fn().mockRejectedValue(new ApiError(422, "The system already creates this line.", null, null));
    render(<Harness onSaveLines={onSaveLines} />);
    await expandAll();
    fireEvent.click(screen.getByRole("button", { name: "New calculation line in Natural gas" }));
    const dialog = screen.getByRole("dialog", { name: "New calculation line in Natural gas" });
    fireEvent.change(within(dialog).getByLabelText("Facility"), { target: { value: "FAC-NW03" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add line" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("The system already creates this line.");
  });

  it("deletes only a reviewer's own line, and says its documents move to Unassigned", async () => {
    const onSaveLines = vi.fn().mockResolvedValue(undefined);
    const onAudit = vi.fn();
    render(<Harness onSaveLines={onSaveLines} onAudit={onAudit} />);
    await expandAll();
    // The system line has no menu; the reviewer's line has Rename and Delete.
    expect(screen.queryByRole("button", { name: "Actions for Natural gas · Kent" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Actions for Natural gas · Plant 2" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Its documents move to Unassigned supporting evidence");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete line" }));
    await waitFor(() => expect(onSaveLines).toHaveBeenCalledWith([]));
    expect(onAudit).toHaveBeenCalledWith(expect.objectContaining({ action: "delete_line" }));
  });

  it("renames a reviewer's own line", async () => {
    const onSaveLines = vi.fn().mockResolvedValue(undefined);
    render(<Harness onSaveLines={onSaveLines} />);
    await expandAll();
    fireEvent.click(screen.getByRole("button", { name: "Actions for Natural gas · Plant 2" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Line name"), { target: { value: "Plant 2 boilers" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(onSaveLines).toHaveBeenCalledWith([{ ...ENGAGEMENT.evidenceLines![0], label: "Plant 2 boilers" }]));
  });

  it("filters by facility through the server, which recounts, and opens the matches", async () => {
    const filteredTree: TreeData = {
      ...TREE,
      blocks: {
        summary: [],
        unassigned: [],
        supporting: {
          scopes: [{ ...TREE.blocks.supporting.scopes[0], counts: counts(1, 1, 4), categories: [{ ...TREE.blocks.supporting.scopes[0].categories[0], counts: counts(1, 1, 4), level2s: [{ ...TREE.blocks.supporting.scopes[0].categories[0].level2s[0], counts: counts(1, 1, 4), lines: [{ line: PLANT, counts: counts(1, 1, 4), documents: [doc("mar")] }] }] }] }],
          unassigned: [],
        },
      },
      set_aside: [],
    };
    mocks.byPath = { [TREE_PATH]: TREE, [`${TREE_PATH}?facility_id=FAC-PL02`]: filteredTree };
    const ids: string[][] = [];
    function Filtered() {
      const [facility, setFacility] = useState<string | null>(null);
      const [open, setOpen] = useState<string[] | null>(null);
      return <Harness facilityId={facility} onFacilityChange={setFacility} openIds={open} onOpenIdsChange={(n) => { ids.push(n); setOpen(n); }} />;
    }
    render(<Filtered />);
    await screen.findByText("Supporting evidence");
    fireEvent.change(screen.getByLabelText("Facility"), { target: { value: "FAC-PL02" } });
    expect(await screen.findByRole("button", { name: "mar.pdf" })).toBeInTheDocument();
    expect(mocks.calls.some((c) => c.path === `${TREE_PATH}?facility_id=FAC-PL02`)).toBe(true);
    expect(screen.queryByRole("button", { name: "feb.pdf" })).toBeNull();
    expect(screen.queryByText("Scope 2")).toBeNull();
    expect(screen.queryByText("Summary documents and workbook")).toBeNull();
    // The counts are the server's, and a row can still be closed while the filter is on.
    expect(screen.getAllByText("25% accepted").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Scope 1" }));
    expect(screen.getByRole("button", { name: "Scope 1" })).toHaveAttribute("aria-expanded", "false");
  });

  it("moves a row whose line was deleted, sending its placement as from and asking nothing", async () => {
    const DEAD = "s1:stationary:natural-gas:fac-gone";
    const orphan = doc("orph", { flags: ["unknown_line"], placement_from: DEAD });
    mocks.byPath = { [TREE_PATH]: { ...TREE, blocks: { ...TREE.blocks, supporting: { ...TREE.blocks.supporting, unassigned: [orphan] } } } };
    const onMovePlacement = vi.fn().mockResolvedValue(undefined);
    render(<Harness onMovePlacement={onMovePlacement} />);
    await expandAll();
    fireEvent.click(screen.getByRole("button", { name: "Actions for orph.pdf" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Move to…" }));
    const dialog = screen.getByRole("dialog", { name: "Move to…" });
    expect(dialog).toHaveTextContent("from Unassigned supporting evidence (its line was deleted)");
    expect(dialog.textContent).not.toContain(DEAD);
    // Where it sits now is not offered as a destination.
    expect(within(dialog).queryByRole("option", { name: "Unassigned supporting evidence" })).toBeNull();
    fireEvent.change(within(dialog).getByLabelText("Move to"), { target: { value: KENT.key } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Move" }));
    expect(screen.getByRole("alert")).toHaveTextContent("4 values move to Natural gas · Kent. Its calculation changes.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm move" }));
    await waitFor(() => expect(onMovePlacement).toHaveBeenCalledWith("orph", { from: DEAD, to: KENT.key }));
  });

  it("offers a new mobile line only on the vehicle groups the server lists", async () => {
    const MOBILE = line("s1:mobile:diesel:vg-fleet-a", "Fleet A (diesel)", { category: "mobile", level2: "diesel", level2_label: "Diesel", anchor_kind: "vehicle_group", anchor_id: "vg-fleet-a" });
    const tree: TreeData = {
      ...TREE,
      blocks: { ...TREE.blocks, supporting: { ...TREE.blocks.supporting, scopes: [{ scope: "s1", label: "Scope 1", counts: counts(0, 0, 0), categories: [{ category: "mobile", label: "Mobile combustion", counts: counts(0, 0, 0), level2s: [] }] }] } },
      lines: [MOBILE],
    };
    mocks.byPath = { [TREE_PATH]: tree };
    const onSaveLines = vi.fn().mockResolvedValue(undefined);
    render(<Harness onSaveLines={onSaveLines} />);
    await expandAll();
    fireEvent.click(screen.getByRole("button", { name: "New fuel" }));
    const dialog = screen.getByRole("dialog", { name: "New fuel in Mobile combustion" });
    fireEvent.change(within(dialog).getByLabelText("Fuel name"), { target: { value: "Biodiesel" } });
    fireEvent.change(within(dialog).getByLabelText("Vehicle group"), { target: { value: "vg-fleet-a" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add fuel" }));
    await waitFor(() =>
      expect(onSaveLines).toHaveBeenCalledWith([
        ...ENGAGEMENT.evidenceLines!,
        { scope: "s1", category: "mobile", level2_label: "Biodiesel", anchor_kind: "vehicle_group", anchor_id: "vg-fleet-a", label: "Fleet A (diesel)" },
      ])
    );
  });

  it("closes a window on Escape and puts the cursor in its first field", async () => {
    render(<Harness />);
    await expandAll();
    fireEvent.click(screen.getByRole("button", { name: "Actions for Natural gas · Plant 2" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));
    expect(screen.getByLabelText("Line name")).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("hands an ended session to the app instead of showing a message", async () => {
    const ended = new ApiError(401, "Session ended.", null, null);
    const onError = vi.fn().mockReturnValue(true);
    render(<Harness onError={onError} onSaveLines={vi.fn().mockRejectedValue(ended)} />);
    await expandAll();
    fireEvent.click(screen.getByRole("button", { name: "Actions for Natural gas · Plant 2" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete line" }));
    await waitFor(() => expect(onError).toHaveBeenCalledWith(ended));
    expect(screen.queryByText(/Not deleted/)).toBeNull();
  });

  it("remembers what is open across a visit elsewhere", async () => {
    const ids: string[][] = [];
    const { unmount } = render(<Harness onOpenIdsChange={(next) => ids.push(next)} openIds={null} />);
    await screen.findByText("Scope 1");
    fireEvent.click(screen.getByRole("button", { name: "Scope 1" }));
    const saved = ids[ids.length - 1];
    expect(saved).not.toContain("scope:s1");
    unmount();
    render(<Harness openIds={saved} onOpenIdsChange={vi.fn()} />);
    await screen.findByText("Scope 1");
    expect(screen.getByRole("button", { name: "Scope 1" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Scope 2" })).toHaveAttribute("aria-expanded", "true");
  });

  it("says what went wrong when the tree does not load, and can try again", async () => {
    mocks.byPath = { [TREE_PATH]: new ApiError(500, "The evidence service is not answering.", null, null) };
    render(<Harness />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The evidence service is not answering.");
    mocks.byPath = { [TREE_PATH]: TREE };
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Supporting evidence")).toBeInTheDocument();
  });
});

describe("the blocks match the design", () => {
  const head = (title: string) => (screen.getByText(title).closest("section") as HTMLElement).querySelector(".s1-et-head") as HTMLElement;

  it("shows Block 1 and Block 2 with a document count and no bar or percent", async () => {
    render(<Harness />);
    await screen.findByText("Summary documents and workbook");
    for (const title of ["Summary documents and workbook", "Unassigned documents"]) {
      const h = head(title);
      expect(within(h).getByText("1 document")).toBeInTheDocument();
      expect(h.querySelector(".s1-et-bar-track")).toBeNull();
      expect(h.textContent).not.toMatch(/%/);
    }
    expect(screen.getByText("Company-prepared, not source evidence")).toBeInTheDocument();
    // Source evidence still shows its bar.
    expect(head("Stationary combustion").querySelector(".s1-et-bar-track")).not.toBeNull();
  });

  it("says what each Unassigned group holds, as plain text and not a state chip", async () => {
    const tree: TreeData = { ...TREE, blocks: { ...TREE.blocks, supporting: { ...TREE.blocks.supporting, unassigned: [doc("parked", { values: 0, accepted: 0 })], unassigned_counts: counts(1, 0, 0) } } };
    mocks.byPath = { [TREE_PATH]: tree };
    render(<Harness />);
    const note = await screen.findByText("Not yet on a calculation line");
    expect(note).toHaveClass("s1-et-sub");
    expect(note).not.toHaveClass("s1-chip");
    expect(screen.getByText("System could not identify these")).toHaveClass("s1-et-sub");
    expect(head("Unassigned supporting evidence").querySelector(".s1-et-bar-track")).not.toBeNull();
  });

  it("shows the full path in Also in, for every line a document is on", async () => {
    const lines = ["Müller Käserei – Zürich", "東京工場", "Plant 3", "Plant 4", "Plant 5"].map((label, i) =>
      line(`s2:purchased_energy:electricity:fac-${i}`, label, { scope: "s2", category: "purchased_energy", level2: "electricity", level2_label: "Electricity" })
    );
    const tree: TreeData = {
      ...TREE,
      lines: [KENT, PLANT, ELEC, ...lines],
      blocks: {
        ...TREE.blocks,
        supporting: {
          ...TREE.blocks.supporting,
          scopes: TREE.blocks.supporting.scopes.map((sc) =>
            sc.scope !== "s1"
              ? sc
              : {
                  ...sc,
                  categories: sc.categories.map((c) => ({
                    ...c,
                    level2s: c.level2s.map((l2) => ({
                      ...l2,
                      lines: l2.lines.map((l) => (l.line.key === KENT.key ? { ...l, documents: [doc("jan", { also_in: lines.map((x) => x.key) })] } : l)),
                    })),
                  })),
                }
          ),
        },
      },
    };
    mocks.byPath = { [TREE_PATH]: tree };
    render(<Harness />);
    await expandAll();
    for (const label of ["Müller Käserei – Zürich", "東京工場", "Plant 3", "Plant 4", "Plant 5"]) {
      const el = screen.getByText(`Also in Scope 2 › Purchased energy › Electricity › ${label}`);
      expect(el).toHaveClass("s1-et-also");
    }
    const css = readFileSync(join(__dirname, "../styles/s1-workpaper.css"), "utf8");
    expect(css).toMatch(/\.s1-et-also\s*{[^}]*overflow-wrap:\s*anywhere/);
  });

  it("falls back to the short title when a label is missing", async () => {
    const bare = line("s2:purchased_energy:electricity:fac-kc01", "Kent", { scope: "s2", category: "purchased_energy", level2: "electricity", level2_label: "" });
    const tree: TreeData = { ...TREE, lines: [KENT, PLANT, bare] };
    mocks.byPath = { [TREE_PATH]: tree };
    render(<Harness />);
    await expandAll();
    expect(screen.getByText("Also in Kent")).toBeInTheDocument();
  });

  it("shows empty states and no bars for an empty engagement", async () => {
    const empty: TreeData = {
      blocks: {
        summary_counts: counts(0, 0, 0),
        unassigned_counts: counts(0, 0, 0),
        summary: [],
        unassigned: [],
        supporting: { scopes: [], unassigned: [], unassigned_counts: counts(0, 0, 0) },
      },
      facilities: [],
      vehicle_groups: [],
      lines: [],
      set_aside: [],
    };
    mocks.byPath = { [TREE_PATH]: empty };
    render(<Harness />);
    await screen.findByText("Summary documents and workbook");
    fireEvent.click(screen.getByRole("button", { name: "Expand all" }));
    expect(screen.getByText("No summary documents yet.")).toBeInTheDocument();
    expect(screen.getAllByText("Nothing here.").length).toBe(2);
    expect(screen.getByText("Not yet on a calculation line")).toBeInTheDocument();
  });

  const NOTE = /No calculation lines yet\. Add your facilities in Setup and each fuel gets one line per facility\./;
  const noFacilities: TreeData = {
    blocks: {
      summary_counts: counts(0, 0, 0),
      unassigned_counts: counts(0, 0, 0),
      summary: [],
      unassigned: [],
      supporting: { scopes: [], unassigned: [], unassigned_counts: counts(0, 0, 0) },
    },
    facilities: [],
    vehicle_groups: [],
    lines: [],
    set_aside: [],
  };

  it("says why there are no lines when the engagement has no facilities, and opens Setup", async () => {
    mocks.byPath = { [TREE_PATH]: noFacilities };
    const onOpenSetup = vi.fn();
    render(<Harness onOpenSetup={onOpenSetup} />);
    const note = await screen.findByText(NOTE);
    // Helper text: the small, regular-weight text style of the other empty states, not a state chip.
    expect(note).toHaveClass("s1-et-none");
    expect(note).not.toHaveClass("s1-chip");
    fireEvent.click(within(note).getByRole("button", { name: "Open Setup" }));
    expect(onOpenSetup).toHaveBeenCalledTimes(1);
  });

  it("shows the note without a button when the page cannot open Setup", async () => {
    mocks.byPath = { [TREE_PATH]: noFacilities };
    render(<Harness />);
    expect(await screen.findByText(NOTE)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Setup" })).toBeNull();
  });

  it("hides the note once there is one facility, including a non-ASCII or CJK name", async () => {
    for (const name of ["Kent", "Müller Käserei – Zürich", "東京工場"]) {
      mocks.byPath = { [TREE_PATH]: { ...noFacilities, facilities: [{ facility_id: "FAC-1", name }] } };
      const { unmount } = render(<Harness />);
      await screen.findByText("Summary documents and workbook");
      expect(screen.queryByText(NOTE)).toBeNull();
      unmount();
    }
  });

  it("does not show the note when the engagement has facilities", async () => {
    mocks.byPath = { [TREE_PATH]: { ...TREE } };
    render(<Harness />);
    await screen.findByText("Summary documents and workbook");
    expect(screen.queryByText(NOTE)).toBeNull();
  });
});

describe("the move confirm says what changes", () => {
  async function openMove(file: string) {
    await expandAll();
    const row = screen.getAllByRole("button", { name: file })[0].closest(".s1-et-doc") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: `Actions for ${file}` }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Move to…" }));
    return screen.getByRole("dialog", { name: "Move to…" });
  }
  const choose = (dialog: HTMLElement, to: string) => fireEvent.change(within(dialog).getByLabelText("Move to"), { target: { value: to } });

  it("counts one value in the singular and names the one line that changes", async () => {
    const one: TreeData = JSON.parse(JSON.stringify(TREE));
    one.blocks.supporting.unassigned = [doc("parked", { file_name: "parked.pdf", values: 1, accepted: 0 })];
    one.blocks.supporting.unassigned_counts = counts(1, 0, 1);
    mocks.byPath = { [TREE_PATH]: one };
    render(<Harness />);
    const dialog = await openMove("parked.pdf");
    choose(dialog, KENT.key);
    fireEvent.click(within(dialog).getByRole("button", { name: "Move" }));
    expect(screen.getByRole("alert")).toHaveTextContent("1 value moves to Natural gas · Kent. Its calculation changes.");
  });

  it("warns, and still allows the move, when the target line calculates another family", async () => {
    const onMovePlacement = vi.fn().mockResolvedValue(undefined);
    render(<Harness onMovePlacement={onMovePlacement} />);
    const dialog = await openMove("feb.pdf");
    expect(within(dialog).queryByRole("status")).toBeNull();
    choose(dialog, ELEC.key);
    expect(within(dialog).getByRole("status")).toHaveTextContent(
      "These values won't count on this line, because it calculates electricity. They will show as not placed."
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Move" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm move" }));
    await waitFor(() => expect(onMovePlacement).toHaveBeenCalledWith("feb", { from: KENT.key, to: ELEC.key }));
  });

  it("does not warn for a target of the same family, a block, or a row with no known family", async () => {
    render(<Harness />);
    const dialog = await openMove("feb.pdf");
    choose(dialog, PLANT.key);
    expect(within(dialog).queryByRole("status")).toBeNull();
    choose(dialog, "supporting:unassigned");
    expect(within(dialog).queryByRole("status")).toBeNull();
  });

  it("says a summary document's values do not feed a line", async () => {
    render(<Harness />);
    const dialog = await openMove("GHG workbook.xlsx");
    choose(dialog, KENT.key);
    expect(within(dialog).getByRole("status")).toHaveTextContent("This is a summary document, and its values don't feed lines.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Move" }));
    expect(screen.getByRole("alert")).toHaveTextContent("This changes the calculation for Natural gas · Kent.");
  });

  it("says why when the target line is one no calculation reads, with non-ASCII names", async () => {
    const odd = line("s1:fugitive:r-404a:fac-zh", "Müller Käserei – Zürich 東京", { category: "fugitive", level2: "r-404a", level2_label: "R-404A", family: null });
    const tree: TreeData = { ...TREE, lines: [...TREE.lines, odd] };
    mocks.byPath = { [TREE_PATH]: tree };
    render(<Harness />);
    const dialog = await openMove("feb.pdf");
    choose(dialog, odd.key);
    expect(within(dialog).getByRole("status")).toHaveTextContent("because no calculation reads this kind of line");
    fireEvent.click(within(dialog).getByRole("button", { name: "Move" }));
    expect(screen.getByRole("alert")).toHaveTextContent("4 values move from Natural gas · Kent to R-404A · Müller Käserei – Zürich 東京.");
  });

  it("counts only the row's own placement for a document on several lines", async () => {
    // "jan" sits on Kent gas (4 values) and on Kent electricity; this row is the gas placement.
    render(<Harness />);
    const dialog = await openMove("jan.pdf");
    choose(dialog, PLANT.key);
    fireEvent.click(within(dialog).getByRole("button", { name: "Move" }));
    expect(screen.getByRole("alert")).toHaveTextContent("4 values move from Natural gas · Kent to Natural gas · Plant 2.");
    // The line it is already on is not offered, so a document is never put twice on one line.
    const options = Array.from((within(dialog).getByLabelText("Move to") as HTMLSelectElement).options).map((o) => o.value);
    expect(options).not.toContain(KENT.key);
  });

  it("says plainly when the document was already moved elsewhere, and saves nothing", async () => {
    const onMovePlacement = vi.fn().mockResolvedValue(undefined);
    render(<Harness onMovePlacement={onMovePlacement} />);
    const dialog = await openMove("feb.pdf");
    choose(dialog, PLANT.key);
    // Meanwhile, in another tab, feb.pdf left Kent.
    const moved: TreeData = JSON.parse(JSON.stringify(TREE));
    moved.blocks.supporting.scopes[0].categories[0].level2s[0].lines[0].documents = [];
    mocks.byPath = { [TREE_PATH]: moved };
    fireEvent.click(within(dialog).getByRole("button", { name: "Move" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm move" }));
    expect(await within(dialog).findByText(/no longer where this page showed it, so nothing was changed/)).toBeInTheDocument();
    expect(onMovePlacement).not.toHaveBeenCalled();
  });
});

describe("moving a placement saves a merged payload", () => {
  it("keeps every other key of the document's saved decision", async () => {
    const before = { documentId: "feb", facilityId: "FAC-PL02", disposition: "active" as const, note: "check", placements: [{ from: "block:unassigned", to: KENT.key }] };
    const saved = await saveDocumentPlacement(ENG, before, "feb", { from: KENT.key, to: PLANT.key });
    const put = mocks.calls.find((c) => c.options?.method === "PUT")!;
    expect(put.path).toBe(`/engagements/${ENG}/workpaper-items/document/feb`);
    expect(put.options?.body).toEqual({
      payload: {
        documentId: "feb",
        facilityId: "FAC-PL02",
        disposition: "active",
        note: "check",
        placements: [
          { from: "block:unassigned", to: KENT.key },
          { from: KENT.key, to: PLANT.key },
        ],
      },
    });
    expect(saved.placements).toHaveLength(2);
  });

  it("starts a decision when the document has none", () => {
    expect(withPlacement(undefined, "x", { from: "a", to: "b" })).toEqual({ documentId: "x", placements: [{ from: "a", to: "b" }] });
  });
});

describe("the evidenceLines setting", () => {
  it("is sent back with every engagement save, so a Setup save does not wipe it", () => {
    expect(engagementToBackend(ENGAGEMENT).settings.evidenceLines).toEqual(ENGAGEMENT.evidenceLines);
  });

  it("survives load, a Setup edit and save", () => {
    const row = {
      id: ENG, org_id: "o", name: "FY", client_name: "Acme", reporting_period_start: "2025-01-01", reporting_period_end: "2025-12-31",
      status: "active" as const, settings: { evidenceLines: ENGAGEMENT.evidenceLines }, created_at: "", updated_at: "",
    };
    const loaded = engagementFromBackend(row);
    expect(loaded.evidenceLines).toEqual(ENGAGEMENT.evidenceLines);
    const edited = { ...loaded, regulation: "CSRD" };
    expect(engagementToBackend(edited).settings.evidenceLines).toEqual(ENGAGEMENT.evidenceLines);
  });
});

describe("Evidence in fixture mode", () => {
  it("keeps today's grouping by document type when no tree is given", () => {
    render(
      <EvidenceWorkspace
        engagement={engagementConfig}
        evidence={manufacturerEvidence}
        asks={[]}
        onSaveAsk={vi.fn()}
        onEvidenceChange={vi.fn()}
        onOpenExtraction={vi.fn()}
      />
    );
    expect(screen.getByText("Client-prepared documents")).toBeInTheDocument();
    expect(screen.queryByText("Supporting evidence")).toBeNull();
    expect(mocks.calls).toHaveLength(0);
  });
});

/* =============================== supporting schedule =============================== */

const SCHEDULE: LineSchedule = {
  line: KENT,
  reporting_period: { start: "2025-01-01", end: "2025-12-31" },
  coverage: [
    { month: "2025-01", status: "counted", quantity: 120, unit: "therm", document_ids: ["jan"] },
    { month: "2025-02", status: "counted_in_part", quantity: 40, unit: "therm", document_ids: ["feb"] },
    { month: "2025-03", status: "not_reviewed", quantity: null, unit: null, document_ids: ["mar", "jan"] },
    { month: "2025-04", status: "no_document", quantity: null, unit: null, document_ids: [] },
  ],
  identifiers: [],
  values: [],
  rows: [
    {
      record_key: "k1",
      accepted: true,
      decision: "accepted",
      date: { start: "2025-01-01", end: "2025-01-31", days: 31, label: "Service period" },
      activity_quantity: { value: 120, unit: "therm" },
      cells: {},
      saved_by: { name: "M. Osei", at: "2025-03-02T10:00:00Z" },
      document_id: "jan",
      file_name: "jan.pdf",
      page: 2,
      candidate_id: "cand-1",
    },
    {
      record_key: "k2",
      accepted: false,
      decision: "not_reviewed",
      date: { start: "2025-02-01", end: "2025-02-28", days: 28, label: "Service period" },
      activity_quantity: { value: 99, unit: "therm" },
      cells: { heat_content: { value: 1.03, unit: "MMBtu/Mcf" } },
      saved_by: null,
      document_id: "feb",
      file_name: "feb.pdf",
      page: 1,
      candidate_id: "cand-2",
    },
    {
      record_key: "k3",
      accepted: false,
      decision: "rejected",
      date: { start: "2025-03-05", end: "2025-03-05", days: 1, label: "Service date" },
      activity_quantity: { value: 5, unit: "therm" },
      cells: {},
      saved_by: null,
      document_id: "mar",
      file_name: "mar.pdf",
      page: null,
      candidate_id: null,
    },
  ],
  columns: [
    { key: "date", label: "Date", unit_in_cells: true },
    { key: "activity_quantity", label: "Activity quantity", unit_in_cells: true },
    { key: "heat_content", label: "Heat content (HHV)", unit_in_cells: true },
  ],
  activity_quantity_note: "Activity quantity: fuel quantity combusted",
  identifier_groups: [
    {
      label: "Account number",
      values: [{ value: "88-1", documents: [{ document_id: "jan", file_name: "jan.pdf" }] }],
      not_found: [],
      documents_with: 11,
      documents_total: 11,
    },
    {
      label: "Meter number",
      values: [
        { value: "M-7", documents: [{ document_id: "jan", file_name: "jan.pdf" }] },
        { value: "M-8", documents: [{ document_id: "feb", file_name: "feb.pdf" }] },
      ],
      not_found: [{ document_id: "mar", file_name: "mar.pdf" }],
      documents_with: 2,
      documents_total: 3,
    },
    {
      label: "Facility",
      values: [{ value: "Kent", documents: [{ document_id: "jan", file_name: "jan.pdf" }] }],
      not_found: [],
      documents_with: 3,
      documents_total: 3,
      matched_by: ["Service address in Setup"],
    },
  ],
  history: [{ at: "2025-03-02T10:00:00Z", text: "M. Osei accepted 120 therm from jan.pdf, page 2" }],
};
const SCHEDULE_PATH = `/engagements/${ENG}/calculation-lines/${encodeURIComponent(KENT.key)}/schedule`;

function renderSchedule(over: Partial<React.ComponentProps<typeof SupportingSchedule>> = {}) {
  const props = { onBack: vi.fn(), onOpenDocument: vi.fn(), onOpenCalculationLine: vi.fn(), ...over };
  render(<SupportingSchedule engagementId={ENG} lineKey={KENT.key} {...props} />);
  return props;
}

describe("the supporting schedule", () => {
  beforeEach(() => {
    mocks.byPath = { [SCHEDULE_PATH]: SCHEDULE };
  });

  it("renders the breadcrumb, title, coverage, identifiers, values and history", async () => {
    renderSchedule();
    expect(await screen.findByRole("heading", { name: "Kent · Natural gas" })).toBeInTheDocument();
    expect(screen.getByText("Supporting schedule")).toBeInTheDocument();
    expect(screen.getByText("Reporting year 2025")).toBeInTheDocument();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(crumbs).toHaveTextContent("Evidence › Scope 1 › Stationary combustion › Natural gas › Kent");
    // Every status has a word, not only a colour.
    const legend = screen.getByRole("list", { name: "Legend" });
    for (const word of ["Counted", "Counted in part", "Not reviewed", "No document"]) expect(within(legend).getByText(word)).toBeInTheDocument();
    expect(screen.getByText("11 of 11 documents")).toBeInTheDocument();
    expect(screen.getByText("2 of 3 documents")).toBeInTheDocument();
    expect(screen.getByText("Activity quantity: fuel quantity combusted")).toBeInTheDocument();
    expect(screen.getByText("Matched by: Service address in Setup")).toBeInTheDocument();
    expect(screen.getByText(/M\. Osei accepted 120 therm from jan\.pdf, page 2/)).toBeInTheDocument();
  });

  it("shows one row per record with units, MM/DD/YY dates, server day counts and a word for each unreviewed row", async () => {
    renderSchedule();
    await screen.findByRole("heading", { name: "Kent · Natural gas" });
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Date", "Activity quantity", "Heat content (HHV)", "Saved by", "Document"]);
    const [, jan, feb, mar] = within(table).getAllByRole("row");
    expect(jan).toHaveTextContent("01/01/25 – 01/31/25 · 31 days");
    expect(jan).toHaveTextContent("120 therm");
    expect(jan).toHaveTextContent("Saved by M. Osei · 03/02/25");
    expect(jan).not.toHaveTextContent("Not reviewed");
    expect(feb).toHaveTextContent("Not reviewed");
    expect(feb).toHaveTextContent("1.03 MMBtu/Mcf");
    expect(mar).toHaveTextContent("03/05/25");
    expect(mar).not.toHaveTextContent("1 day");
    expect(mar).toHaveTextContent("Rejected");
    expect(within(table).queryByRole("textbox")).toBeNull();
  });

  it("shows the server's numbers as given, marks edited rows, labels the date and aligns text left", async () => {
    const one = SCHEDULE.rows[0];
    mocks.byPath = {
      [SCHEDULE_PATH]: {
        ...SCHEDULE,
        columns: [
          ...SCHEDULE.columns,
          { key: "model_year", label: "Model year", unit_in_cells: false },
          { key: "vehicle_type", label: "Vehicle type", unit_in_cells: false },
        ],
        rows: [
          {
            ...one,
            decision: "edited",
            cells: { model_year: { value: 2019 }, heat_content: { value: 1.0312345, unit: "MMBtu/Mcf" }, vehicle_type: { value: "Van" } },
          },
        ],
        identifier_groups: [{ ...SCHEDULE.identifier_groups[0], values: [{ value: " ", documents: [] }] }],
      },
    };
    renderSchedule();
    await screen.findByRole("heading", { name: "Kent · Natural gas" });
    const table = screen.getByRole("table");
    expect(within(table).getByRole("columnheader", { name: "Service period" })).toBeInTheDocument();
    const [, row] = within(table).getAllByRole("row");
    expect(row).toHaveTextContent("2019");
    expect(row).not.toHaveTextContent("2,019");
    expect(row).toHaveTextContent("1.0312345 MMBtu/Mcf");
    expect(row).toHaveTextContent("Edited");
    expect(row).not.toHaveClass("s1-sch-row--pending");
    expect(within(table).getByRole("columnheader", { name: "Vehicle type" })).not.toHaveClass("s1-num");
    expect(within(table).getByRole("columnheader", { name: "Model year" })).toHaveClass("s1-num");
    fireEvent.click(screen.getByRole("button", { name: /Account number/ }));
    expect(screen.getAllByText(/Not found/).length).toBeGreaterThan(0);
  });

  it("groups an identifier's documents by value, with Not found, and opens each document", async () => {
    const props = renderSchedule();
    const toggle = await screen.findByRole("button", { name: /Meter number/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("M-8 · 1 document")).toBeInTheDocument();
    expect(screen.getByText("Not found · 1 document")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Open mar.pdf" })[0]);
    expect(props.onOpenDocument).toHaveBeenCalledWith("mar");
  });

  it("keeps a short identifier summary on one line, so it never breaks mid-word", async () => {
    renderSchedule();
    const toggle = await screen.findByRole("button", { name: /Meter number/ });
    const value = toggle.querySelector(".s1-sch-ids__value") as HTMLElement;
    expect(value.className).toContain("s1-sch-ids__value--short");
    const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");
    expect(css).toMatch(/\.s1-sch-ids__value--short\s*\{[^}]*white-space:\s*nowrap/);
    expect(css).not.toMatch(/\.s1-sch-ids__value\s*\{[^}]*overflow-wrap:\s*anywhere/);
  });

  it("opens a month's document when the month is clicked", async () => {
    const props = renderSchedule();
    const month = await screen.findByRole("button", { name: /^Feb 2025: Counted in part/ });
    fireEvent.click(month);
    expect(props.onOpenDocument).toHaveBeenCalledWith("feb");
    expect(screen.queryByRole("button", { name: /^Apr 2025/ })).toBeNull();
  });

  it("lists every document of a month that has several", async () => {
    const props = renderSchedule();
    await screen.findByRole("heading", { name: "Kent · Natural gas" });
    fireEvent.click(screen.getByRole("button", { name: "Mar 2025: open mar.pdf" }));
    expect(props.onOpenDocument).toHaveBeenCalledWith("mar");
    fireEvent.click(screen.getByRole("button", { name: "Mar 2025: open jan.pdf" }));
    expect(props.onOpenDocument).toHaveBeenCalledWith("jan");
  });

  it("opens the extraction review at the value from the document icon", async () => {
    const props = renderSchedule();
    fireEvent.click(await screen.findByRole("button", { name: "Open jan.pdf, page 2 at this value" }));
    expect(props.onOpenDocument).toHaveBeenCalledWith("jan", "candidate:cand-1");
  });

  it("goes back to Evidence and to the calculation line through its callbacks", async () => {
    const props = renderSchedule();
    fireEvent.click(await screen.findByRole("button", { name: "Open calculation line ›" }));
    expect(props.onOpenCalculationLine).toHaveBeenCalledWith(KENT.key);
    fireEvent.click(screen.getAllByRole("button", { name: /Back to evidence|^Evidence$/i })[0]);
    expect(props.onBack).toHaveBeenCalled();
  });

  it("says what a row and a month are waiting on, and disables the calculation link, with the reason, when the line is not calculated", async () => {
    const [first, second, third] = SCHEDULE.rows;
    mocks.byPath = {
      [SCHEDULE_PATH]: {
        ...SCHEDULE,
        calculated: false,
        coverage: [
          { month: "2025-03", status: "not_reviewed", quantity: null, unit: null, document_ids: ["mar"], waiting_on: ["Fuel type"] },
        ],
        rows: [
          { ...first, accepted: false, decision: "awaiting_other_fields", waiting_on: ["Fuel type"] },
          second,
          third,
        ],
      },
    };
    const props = renderSchedule();
    await screen.findByRole("heading", { name: "Kent · Natural gas" });
    expect(screen.getAllByText("Waiting on: Fuel type")).toHaveLength(2); // the month and the row
    expect(screen.getByText("Not calculated yet: values on this line are waiting for review.")).toBeInTheDocument();
    const link = screen.getByRole("button", { name: "Open calculation line ›" });
    expect(link).toBeDisabled();
    expect(link).toHaveAccessibleDescription("Not calculated yet: values on this line are waiting for review.");
    fireEvent.click(link);
    expect(props.onOpenCalculationLine).not.toHaveBeenCalled();
  });

  it("uses neutral copy for an empty line that is not calculated, and says Rejected for a rejected field", async () => {
    mocks.byPath = { [SCHEDULE_PATH]: { ...SCHEDULE, calculated: false, rows: [], coverage: [], values: [] } };
    const { unmount } = render(<SupportingSchedule engagementId={ENG} lineKey={KENT.key} onBack={vi.fn()} onOpenDocument={vi.fn()} onOpenCalculationLine={vi.fn()} />);
    expect(await screen.findByText("No calculation for this line yet.")).toBeInTheDocument();
    expect(screen.queryByText(/waiting for review/)).toBeNull();
    unmount();
    const [first] = SCHEDULE.rows;
    mocks.byPath = {
      [SCHEDULE_PATH]: { ...SCHEDULE, calculated: false, rows: [{ ...first, accepted: false, decision: "awaiting_other_fields", rejected_fields: ["Fuel type"], waiting_on: [] }] },
    };
    renderSchedule();
    expect(await screen.findByText("Rejected: Fuel type")).toBeInTheDocument();
    expect(screen.queryByText(/Waiting on/)).toBeNull();
  });

  it("stacks the sections in the spec's order: header, coverage, identifiers, values, history", async () => {
    const { container } = render(<SupportingSchedule engagementId={ENG} lineKey={KENT.key} onBack={vi.fn()} onOpenDocument={vi.fn()} onOpenCalculationLine={vi.fn()} />);
    await screen.findByRole("heading", { name: "Kent · Natural gas" });
    const order = [...container.querySelectorAll("header.s1-sch-head, section[aria-label], details.s1-sch-history")].map((e) => e.getAttribute("aria-label") ?? e.tagName.toLowerCase());
    expect(order).toEqual(["header", "Coverage by month", "Source identifiers", "Accepted values", "details"]);
    // Siblings in one column: nothing is wrapped in a side-by-side band.
    expect(container.querySelector(".s1-sch-top")).toBeNull();
  });

  it("still offers the calculation link, with a plain reason, on a line with 0 values", async () => {
    mocks.byPath = { [SCHEDULE_PATH]: { ...SCHEDULE, calculated: false, rows: [], values: [], coverage: [], history: [] } };
    renderSchedule();
    const link = await screen.findByRole("button", { name: "Open calculation line ›" });
    expect(link).toBeDisabled();
    expect(screen.getByText("No calculation for this line yet.")).toBeInTheDocument();
    expect(screen.getByText("No values have been extracted on this line yet.")).toBeInTheDocument();
  });

  it("keeps non-ASCII line names in the title and breadcrumb, and a two-year period readable", async () => {
    const muller = { ...KENT, label: "Müller Fabrik", level2_label: "Erdgas" };
    mocks.byPath = {
      [SCHEDULE_PATH]: {
        ...SCHEDULE,
        line: muller,
        reporting_period: { start: "2024-07-01", end: "2025-06-30" },
        rows: [{ ...SCHEDULE.rows[0], date: { start: "2024-12-17", end: "2025-01-16", days: 31, label: "Service period" } }],
      },
    };
    renderSchedule();
    expect(await screen.findByRole("heading", { name: "Müller Fabrik · Erdgas" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toHaveTextContent("Evidence › Scope 1 › Stationary combustion › Erdgas › Müller Fabrik");
    expect(screen.getByText("Reporting year 2024 to 2025")).toBeInTheDocument();
    expect(screen.getByRole("table")).toHaveTextContent("12/17/24 – 01/16/25 · 31 days");
  });

  it("writes history times as MM/DD/YY, HH:MM", async () => {
    mocks.byPath = { [SCHEDULE_PATH]: { ...SCHEDULE, history: [{ at: "2025-11-04T09:12:00", text: "J. Park added 55,700 therm" }, { at: "not a date", text: "Odd entry" }] } };
    renderSchedule();
    fireEvent.click(await screen.findByText(/Line history/));
    expect(screen.getByText("11/04/25, 09:12")).toBeInTheDocument();
    expect(screen.getByText("not a date")).toBeInTheDocument();
  });

  it("shows the same local day in Saved by and in the line history for a timestamp near midnight UTC", async () => {
    const at = "2025-03-02T23:30:00Z";
    mocks.byPath = { [SCHEDULE_PATH]: { ...SCHEDULE, rows: [{ ...SCHEDULE.rows[0], saved_by: { name: "Zoë Ångström", at } }], history: [{ at, text: "Zoë Ångström accepted 120 therm" }] } };
    renderSchedule();
    const d = new Date(at);
    const day = `${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")}/25`;
    expect(await screen.findByText(`Saved by Zoë Ångström · ${day}`)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/Line history/));
    expect(screen.getByText(new RegExp(`^${day}, \\d{2}:\\d{2}$`))).toBeInTheDocument();
  });

  it("puts the back link first, left-aligned, above the title block and the calculation button", async () => {
    const { container } = render(<SupportingSchedule engagementId={ENG} lineKey={KENT.key} onBack={vi.fn()} onOpenDocument={vi.fn()} onOpenCalculationLine={vi.fn()} />);
    await screen.findByRole("heading", { name: "Kent · Natural gas" });
    const section = container.querySelector(".s1-sch") as HTMLElement;
    const back = within(section).getByRole("button", { name: /Back to evidence/i });
    expect(section.firstElementChild).toBe(back);
    expect(container.querySelector(".s1-sch-head")?.contains(back)).toBe(false);
  });

  it("says '1 of 1 document' in the singular, and 'documents' otherwise", async () => {
    mocks.byPath = { [SCHEDULE_PATH]: { ...SCHEDULE, identifier_groups: [{ ...SCHEDULE.identifier_groups[0], documents_with: 1, documents_total: 1 }, SCHEDULE.identifier_groups[1]] } };
    renderSchedule();
    expect(await screen.findByText("1 of 1 document")).toBeInTheDocument();
    expect(screen.getByText("2 of 3 documents")).toBeInTheDocument();
  });

  it("shows a plain loading line, not placeholder rows, while the schedule loads", () => {
    mocks.byPath = { [SCHEDULE_PATH]: new Promise(() => undefined) as unknown as LineSchedule };
    render(<SupportingSchedule engagementId={ENG} lineKey={KENT.key} onBack={vi.fn()} onOpenDocument={vi.fn()} onOpenCalculationLine={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading the supporting schedule.");
    expect(screen.queryByText("Loading row")).toBeNull();
  });

  it("styles values at one size and month names in the regular weight", () => {
    const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");
    // The quantity cell (class s1-num, 12px by default) is raised to the body size the date cell has.
    expect(css).toMatch(/\.s1-sch-values td\.s1-num\s*\{[^}]*font-size:\s*var\(--text-md\)/);
    // Bold is for structure: no month label rule uses the strong weight.
    const rules = css.match(/\.s1-sch-month__name\s*\{[^}]*\}/g) ?? [];
    expect(rules.length).toBeGreaterThan(0);
    for (const rule of rules) expect(rule).not.toContain("--weight-strong");
  });

  it("round-trips a line key with : . - between results and the schedule", async () => {
    const key = "s1:stationary:natural-gas:fac-k.c-01";
    const encoded = `/engagements/${ENG}/calculation-lines/${encodeURIComponent(key)}/schedule`;
    mocks.byPath = { [encoded]: { ...SCHEDULE, line: { ...KENT, key } } };
    const onOpenCalculationLine = vi.fn();
    render(<SupportingSchedule engagementId={ENG} lineKey={key} onBack={vi.fn()} onOpenDocument={vi.fn()} onOpenCalculationLine={onOpenCalculationLine} />);
    fireEvent.click(await screen.findByRole("button", { name: "Open calculation line ›" }));
    const results = resultsViewForLine(onOpenCalculationLine.mock.calls[0][0]);
    expect(results.lineKey).toBe(key);
    expect(scheduleViewForLine(results.lineKey).lineKey).toBe(key);
    expect(mocks.calls.some((c) => c.path === encoded)).toBe(true);
  });

  it("shows the load error, not an empty schedule, when the v2 fields are missing", async () => {
    const old: Partial<LineSchedule> = { ...SCHEDULE };
    delete old.rows;
    mocks.byPath = { [SCHEDULE_PATH]: old as LineSchedule };
    renderSchedule();
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't load this schedule");
    expect(screen.queryByText("No values have been extracted on this line yet.")).toBeNull();
  });

  it("says what went wrong when the schedule does not load", async () => {
    mocks.byPath = { [SCHEDULE_PATH]: new ApiError(404, "That calculation line does not exist.", null, null) };
    renderSchedule();
    expect(await screen.findByRole("alert")).toHaveTextContent("That calculation line does not exist.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

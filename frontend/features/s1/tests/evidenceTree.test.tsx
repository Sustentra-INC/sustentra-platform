/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const KENT = line("s1:stationary:natural-gas:fac-kc01", "Kent");
const PLANT = line("s1:stationary:natural-gas:fac-pl02", "Plant 2", { created_by_user: true });
const ELEC = line("s2:purchased_energy:electricity:fac-kc01", "Kent", { scope: "s2", category: "purchased_energy", level2: "electricity", level2_label: "Electricity" });

const TREE: TreeData = {
  blocks: {
    summary: [doc("workbook", { file_name: "GHG workbook.xlsx", detected_type: "Inventory workbook", values: 0, accepted: 0 })],
    unassigned: [doc("scan", { file_name: "scan-001.pdf", processing_status: "failed", detected_type: null, facility_id: null, facility_name: null, values: 0, accepted: 0 })],
    supporting: {
      scopes: [
        {
          scope: "s1",
          label: "Scope 1",
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
  facilities: [{ facility_id: "FAC-KC01", name: "Kent" }],
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
  evidenceLines: [{ scope: "s1", category: "stationary", level2_label: "Natural gas", anchor_kind: "facility", anchor_id: "FAC-PL02", label: "Plant 2" }],
};

function Harness(over: Partial<EvidenceTreeProps> = {}) {
  const [open, setOpen] = useState<string[] | null>(null);
  return (
    <EvidenceTree
      engagement={ENGAGEMENT}
      reloadKey="a"
      visibleDocumentIds={null}
      onClearFilter={vi.fn()}
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
    expect(screen.getByText("Added by a reviewer")).toBeInTheDocument();
    expect(screen.getByText(/Also in Electricity · Kent/)).toBeInTheDocument();
    expect(screen.getByText("Set aside")).toBeInTheDocument();
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
    expect(screen.getByRole("alert")).toHaveTextContent("This changes the calculation for Natural gas · Kent and Natural gas · Plant 2");
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

  it("keeps only the documents a facility filter lets through", async () => {
    render(<Harness visibleDocumentIds={new Set(["mar"])} />);
    expect(await screen.findByRole("button", { name: "mar.pdf" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "feb.pdf" })).toBeNull();
    expect(screen.queryByText("Scope 2")).toBeNull();
    expect(screen.queryByText("Summary documents and workbook")).toBeNull();
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
    { month: "2025-03", status: "not_reviewed", quantity: null, unit: null, document_ids: ["mar"] },
    { month: "2025-04", status: "no_document", quantity: null, unit: null, document_ids: [] },
  ],
  identifiers: [
    { label: "Account number", value: "88-1", documents_with: 11, documents_total: 11 },
    { label: "Meter number", value: "M-7", documents_with: 9, documents_total: 11 },
  ],
  values: [
    {
      service_period_start: "2025-01-01",
      service_period_end: "2025-01-31",
      days: 31,
      quantity: 120,
      unit: "therm",
      document_id: "jan",
      file_name: "jan.pdf",
      page: 2,
      candidate_id: "cand-1",
      decided_by: "M. Osei",
      decided_at: "2025-03-02T10:00:00Z",
      decision: "accepted",
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
    expect(screen.getByText("11/11 documents")).toBeInTheDocument();
    expect(screen.getByText("9/11 documents · not on all")).toBeInTheDocument();
    expect(screen.getByText("Accepted by M. Osei · Mar 2, 2025")).toBeInTheDocument();
    expect(screen.getByText(/M\. Osei accepted 120 therm from jan\.pdf, page 2/)).toBeInTheDocument();
  });

  it("opens a month's document when the month is clicked", async () => {
    const props = renderSchedule();
    const month = await screen.findByRole("button", { name: /^Feb 2025: Counted in part/ });
    fireEvent.click(month);
    expect(props.onOpenDocument).toHaveBeenCalledWith("feb");
    expect(screen.queryByRole("button", { name: /^Apr 2025/ })).toBeNull();
  });

  it("opens the extraction review at the value from the document icon", async () => {
    const props = renderSchedule();
    fireEvent.click(await screen.findByRole("button", { name: "Open jan.pdf, page 2 at this value" }));
    expect(props.onOpenDocument).toHaveBeenCalledWith("jan", "cand-1");
  });

  it("goes back to Evidence and to the calculation line through its callbacks", async () => {
    const props = renderSchedule();
    fireEvent.click(await screen.findByRole("button", { name: "Open calculation line ›" }));
    expect(props.onOpenCalculationLine).toHaveBeenCalledWith(KENT.key);
    fireEvent.click(screen.getAllByRole("button", { name: /Back to Evidence|^Evidence$/ })[0]);
    expect(props.onBack).toHaveBeenCalled();
  });

  it("says what went wrong when the schedule does not load", async () => {
    mocks.byPath = { [SCHEDULE_PATH]: new ApiError(404, "That calculation line does not exist.", null, null) };
    renderSchedule();
    expect(await screen.findByRole("alert")).toHaveTextContent("That calculation line does not exist.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

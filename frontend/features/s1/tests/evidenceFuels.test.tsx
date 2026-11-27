/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ byPath: {} as Record<string, unknown> }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn((path: string) => {
    const value = mocks.byPath[path];
    return value instanceof Error ? Promise.reject(value) : Promise.resolve(value ?? {});
  }),
}));

import { ApiError } from "../../../lib/api";
import type { CalculationLine, EvidenceTree as TreeData, TreeCounts, TreeLevel2 } from "../api/evidenceTree";
import { EvidenceTree, type EvidenceTreeProps } from "../components/EvidenceTree";
import { AssignTaskProvider } from "../../tasks/AssignTaskContext";
import { engagementConfig } from "../fixtures/engagementConfig";
import { createdByText } from "../utils/formatPeriod";
import type { EngagementConfig } from "../types";

/** MVP-145: rename and delete a fuel (Level 2) on the Evidence tree. */
const ENG = "eng-1";
const TREE_PATH = `/engagements/${ENG}/evidence-tree`;
const SYSTEM_TIP = "Created by the system from your Setup; can't be deleted.";

const counts = (documents: number): TreeCounts => ({ documents, values: documents * 4, accepted: documents * 2, to_review: documents * 2, issues: 0, pct_accepted: 50 });

const line = (level2: string, level2_label: string, anchor: string, label: string, byUser: boolean): CalculationLine => ({
  key: `s1:stationary:${level2}:${anchor}`,
  scope: "s1",
  category: "stationary",
  level2,
  level2_label,
  anchor_kind: "facility",
  anchor_id: anchor.toUpperCase(),
  label,
  facility_id: null,
  created_by_user: byUser,
  family: "stationary",
});

const GAS = line("natural-gas", "Natural gas", "fac-kc01", "Kent", false);
const PROPANE = line("propane", "Propane", "fac-kc01", "Kent", true);

const doc = (id: string) => ({
  document_id: id, file_name: `${id}.pdf`, period_start: "2025-01-01", period_end: "2025-01-31", facility_id: "FAC-KC01", facility_name: "Kent",
  processing_status: "completed", detected_type: "Natural gas bill", also_in: [], value_family: "stationary" as const, values: 4, accepted: 2, flags: [],
});

const GAS_NODE: TreeLevel2 = { level2: "natural-gas", label: "Natural gas", counts: counts(1), created_by_user: false, lines: [{ line: GAS, counts: counts(1), documents: [doc("jan")] }] };
const PROPANE_NODE: TreeLevel2 = {
  level2: "propane",
  label: "Propane",
  counts: counts(3),
  created_by_user: true,
  created_by: "u1",
  created_by_name: "Jane Park",
  created_at: "2025-11-04T12:00:00Z",
  lines: [{ line: PROPANE, counts: counts(3), documents: [doc("a"), doc("b"), doc("c")] }],
};

function tree(level2s: TreeLevel2[]): TreeData {
  return {
    blocks: {
      summary_counts: counts(0),
      unassigned_counts: counts(0),
      summary: [],
      unassigned: [],
      supporting: { scopes: [{ scope: "s1", label: "Scope 1", counts: counts(4), categories: [{ category: "stationary", label: "Stationary combustion", counts: counts(4), level2s }] }], unassigned: [] },
    },
    facilities: [{ facility_id: "FAC-KC01", name: "Kent" }],
    vehicle_groups: [],
    lines: level2s.flatMap((l) => l.lines.map((n) => n.line)),
    set_aside: [],
  } as unknown as TreeData;
}

const ENGAGEMENT: EngagementConfig = { ...engagementConfig, engagementId: ENG, facilities: [{ facilityId: "FAC-KC01", name: "Kent" }] };

function Harness(over: Partial<EvidenceTreeProps> = {}) {
  const [open, setOpen] = useState<string[] | null>(null);
  return (
    <AssignTaskProvider orgId={null} engagementId={null}>
      <EvidenceTree
        tab="supporting"
        onTabChange={vi.fn()}
        engagement={ENGAGEMENT}
        reloadKey="a"
        facilityId={null}
        onFacilityChange={vi.fn()}
        openIds={open}
        onOpenIdsChange={setOpen}
        onOpenExtraction={vi.fn()}
        onOpenSchedule={vi.fn()}
        onMovePlacement={vi.fn().mockResolvedValue(undefined)}
        onCreateLine={vi.fn().mockResolvedValue(undefined)}
        onRenameLine={vi.fn().mockResolvedValue(undefined)}
        onDeleteLine={vi.fn().mockResolvedValue(0)}
        onRenameFuel={vi.fn().mockResolvedValue(undefined)}
        onDeleteFuel={vi.fn().mockResolvedValue(0)}
        writesEnabled
        {...over}
      />
    </AssignTaskProvider>
  );
}

beforeEach(() => {
  mocks.byPath = { [TREE_PATH]: tree([GAS_NODE, PROPANE_NODE]) };
});
afterEach(cleanup);

const menuOf = async (name: string) => {
  fireEvent.click(await screen.findByRole("button", { name: `Actions for ${name}` }));
  return screen.findByRole("menu");
};

describe("a fuel's row menu", () => {
  it("has Rename and Delete on a fuel, and a menu on the system's fuel too", async () => {
    render(<Harness />);
    await screen.findByText("Propane");
    const menu = await menuOf("Propane");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Rename", "Delete"]);
    expect(within(menu).getByRole("menuitem", { name: "Delete" })).not.toHaveAttribute("aria-disabled");
  });

  it("shows who created a reviewer's fuel as a muted label, and nothing on the system's", async () => {
    render(<Harness />);
    await screen.findByText("Propane");
    expect(screen.getByText(createdByText("Jane Park", "2025-11-04T12:00:00Z"))).toBeInTheDocument();
    expect(createdByText("Jane Park", "2025-11-04T12:00:00Z")).toMatch(/^Created by J\. Park · Nov \d+$/);
    expect(screen.queryAllByText(/^Created by/)).toHaveLength(1);
  });

  it("says why the system's fuel can't be deleted, and does nothing when it is chosen", async () => {
    const onDeleteFuel = vi.fn().mockResolvedValue(0);
    render(<Harness onDeleteFuel={onDeleteFuel} />);
    await screen.findByText("Natural gas");
    const menu = await menuOf("Natural gas");
    const remove = within(menu).getByRole("menuitem", { name: "Delete" });
    expect(remove).toHaveAttribute("aria-disabled", "true");
    expect(remove).toHaveAttribute("title", SYSTEM_TIP);
    expect(within(menu).getByRole("menuitem", { name: "Rename" })).not.toHaveAttribute("title");
    fireEvent.click(remove);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onDeleteFuel).not.toHaveBeenCalled();
  });

  it("describes the unavailable Delete by visible text in the menu, and stays open when it is chosen", async () => {
    render(<Harness />);
    await screen.findByText("Natural gas");
    const menu = await menuOf("Natural gas");
    const remove = within(menu).getByRole("menuitem", { name: "Delete" });
    const hint = document.getElementById(remove.getAttribute("aria-describedby") ?? "none");
    expect(hint).not.toBeNull();
    expect(menu).toContainElement(hint);
    expect(hint).toBeVisible();
    expect(hint).toHaveTextContent("Created by the system from your Setup; can't be deleted");
    fireEvent.click(remove);
    expect(screen.getByRole("menu")).toBeInTheDocument(); // never closes silently
    expect(hint).toBeVisible();
    // the entry that can be used has no hint
    expect(within(menu).getByRole("menuitem", { name: "Rename" })).not.toHaveAttribute("aria-describedby");
  });

  it("works by keyboard: the first item has the cursor, arrows reach Delete, Escape returns to the button", async () => {
    render(<Harness />);
    await screen.findByText("Natural gas");
    const trigger = await screen.findByRole("button", { name: "Actions for Natural gas" });
    fireEvent.click(trigger);
    const menu = await screen.findByRole("menu");
    await waitFor(() => expect(within(menu).getByRole("menuitem", { name: "Rename" })).toHaveFocus());
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(within(menu).getByRole("menuitem", { name: "Delete" })).toHaveFocus(); // reachable, so its reason can be read
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(within(menu).getByRole("menuitem", { name: "Rename" })).toHaveFocus();
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("has no menu without the server actions, without write access, or under a facility filter", async () => {
    const { unmount } = render(<Harness onRenameFuel={undefined} onDeleteFuel={undefined} />);
    await screen.findByText("Propane");
    expect(screen.queryByRole("button", { name: "Actions for Propane" })).toBeNull();
    unmount();
    const second = render(<Harness writesEnabled={false} />);
    await screen.findByText("Propane");
    expect(screen.queryByRole("button", { name: "Actions for Propane" })).toBeNull();
    second.unmount();
    mocks.byPath[`${TREE_PATH}?facility_id=FAC-KC01`] = tree([GAS_NODE, PROPANE_NODE]);
    render(<Harness facilityId="FAC-KC01" />);
    await screen.findByText("Propane");
    expect(screen.queryByRole("button", { name: "Actions for Propane" })).toBeNull();
  });
});

describe("renaming a fuel", () => {
  async function open(name = "Propane") {
    await screen.findByText(name);
    await menuOf(name);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Rename" }));
    const dialog = screen.getByRole("dialog");
    return { dialog, field: within(dialog).getByLabelText("Fuel name") as HTMLInputElement, save: within(dialog).getByRole("button", { name: "Rename" }) };
  }

  it("takes at most 80 characters, starts on the current name, and waits for a different one", async () => {
    render(<Harness />);
    const { field, save } = await open();
    expect(field).toHaveFocus();
    expect(field.value).toBe("Propane");
    expect(field.maxLength).toBe(80);
    expect(save).toBeDisabled(); // unchanged
    fireEvent.change(field, { target: { value: "   " } });
    expect(save).toBeDisabled(); // empty once trimmed
  });

  it("sends the trimmed name with the fuel's category and id, and closes", async () => {
    const onRenameFuel = vi.fn().mockResolvedValue(undefined);
    render(<Harness onRenameFuel={onRenameFuel} />);
    const { field, save } = await open();
    fireEvent.change(field, { target: { value: "  燃料 <b>LPG</b>  " } });
    fireEvent.click(save);
    await waitFor(() => expect(onRenameFuel).toHaveBeenCalledWith("stationary", "propane", "燃料 <b>LPG</b>"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("refuses a name another fuel of the category has, ignoring case, before asking the server", async () => {
    const onRenameFuel = vi.fn().mockResolvedValue(undefined);
    render(<Harness onRenameFuel={onRenameFuel} />);
    const { dialog, field, save } = await open();
    fireEvent.change(field, { target: { value: " natural GAS " } });
    expect(within(dialog).getByRole("alert")).toHaveTextContent("natural GAS already exists in Stationary combustion.");
    expect(save).toBeDisabled();
    expect(onRenameFuel).not.toHaveBeenCalled();
    fireEvent.change(field, { target: { value: "LPG" } });
    expect(within(dialog).queryByRole("alert")).toBeNull();
    expect(save).toBeEnabled();
  });

  it("shows the server's refusal in the window and keeps it open", async () => {
    const onRenameFuel = vi.fn().mockRejectedValue(new ApiError(409, "LPG already exists in this category. Use another name.", {}, null));
    render(<Harness onRenameFuel={onRenameFuel} />);
    const { dialog, field, save } = await open();
    fireEvent.change(field, { target: { value: "LPG" } });
    fireEvent.click(save);
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Not saved. LPG already exists in this category. Use another name.");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("renames the system's fuel too", async () => {
    const onRenameFuel = vi.fn().mockResolvedValue(undefined);
    render(<Harness onRenameFuel={onRenameFuel} />);
    const { field, save } = await open("Natural gas");
    fireEvent.change(field, { target: { value: "Pipeline gas" } });
    fireEvent.click(save);
    await waitFor(() => expect(onRenameFuel).toHaveBeenCalledWith("stationary", "natural-gas", "Pipeline gas"));
  });

  it("closes on Escape", async () => {
    render(<Harness />);
    await open();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("deleting a fuel", () => {
  async function open(name = "Propane") {
    await screen.findByText(name);
    await menuOf(name);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    return screen.queryByRole("dialog");
  }

  it("asks first, naming the documents that move and that their values stop counting", async () => {
    render(<Harness />);
    const dialog = await open();
    expect(dialog).toHaveAccessibleName("Delete Propane?");
    expect(dialog).toHaveTextContent("Its 3 documents move to Unassigned supporting evidence. Their values stop counting until you place them again.");
  });

  it("says it in the singular for one document, and plainly for none", async () => {
    mocks.byPath = { [TREE_PATH]: tree([GAS_NODE, { ...PROPANE_NODE, counts: counts(1) }]) };
    const first = render(<Harness />);
    expect(await open()).toHaveTextContent("Its 1 document moves to Unassigned supporting evidence. Its value stops counting until you place it again.");
    first.unmount();
    mocks.byPath = { [TREE_PATH]: tree([GAS_NODE, { ...PROPANE_NODE, counts: counts(0) }]) };
    render(<Harness />);
    expect(await open()).toHaveTextContent("It has no documents.");
  });

  it("deletes with the fuel's category and id once confirmed, and not before", async () => {
    const onDeleteFuel = vi.fn().mockResolvedValue(3);
    render(<Harness onDeleteFuel={onDeleteFuel} />);
    const dialog = await open();
    expect(onDeleteFuel).not.toHaveBeenCalled();
    fireEvent.click(within(dialog!).getByRole("button", { name: "Delete fuel" }));
    await waitFor(() => expect(onDeleteFuel).toHaveBeenCalledWith("stationary", "propane"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("changes nothing on Cancel, and shows the server's refusal in the window", async () => {
    const onDeleteFuel = vi.fn().mockRejectedValue(new ApiError(409, SYSTEM_TIP, { detail: { code: "level2_system_created", message: SYSTEM_TIP } }, null));
    render(<Harness onDeleteFuel={onDeleteFuel} />);
    const dialog = await open();
    fireEvent.click(within(dialog!).getByRole("button", { name: "Delete fuel" }));
    expect(await within(dialog!).findByRole("alert")).toHaveTextContent(`Not deleted. ${SYSTEM_TIP}`);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(onDeleteFuel).toHaveBeenCalledTimes(1);
  });
});

describe("a refusal with a code reads as its sentence", () => {
  it("is the message of the error the app shows", async () => {
    const original = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
    const fetcher = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      headers: new Headers(),
      json: async () => ({ detail: { code: "level2_system_created", message: SYSTEM_TIP } }),
    });
    vi.stubGlobal("fetch", fetcher);
    try {
      const failure = await original.api("/x").catch((e: unknown) => e);
      expect(failure).toBeInstanceOf(original.ApiError);
      expect((failure as ApiError).detail).toBe(SYSTEM_TIP);
      expect(((failure as ApiError).body as { detail: { code: string } }).detail.code).toBe("level2_system_created");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

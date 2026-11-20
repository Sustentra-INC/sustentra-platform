/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ tree: null as unknown, calls: [] as { path: string; options?: { method?: string; body?: unknown } }[] }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn((path: string, options?: { method?: string; body?: unknown }) => {
    mocks.calls.push({ path, options });
    return Promise.resolve(path.endsWith("/evidence-tree") ? mocks.tree : {});
  }),
}));

import type { EvidenceTree as TreeData, TreeDocRow } from "../api/evidenceTree";
import { demoApi } from "../demo-backend";
import { setDemoEngagement } from "../demo-backend/state";
import { AiFacilityNote } from "../components/AiFacilityNote";
import { EvidenceTree } from "../components/EvidenceTree";
import { ExtractionReview } from "../components/ExtractionReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerValues } from "../fixtures/extraction/manufacturerValues";
import { setDocumentFacility } from "../api/evidenceTree";
import { engagementActivity } from "../utils/engagementActivity";
import type { EngagementConfig } from "../types";

const ENG = "eng-1";
const doc = (over: Partial<TreeDocRow> = {}): TreeDocRow => ({
  document_id: "LOG",
  file_name: "Käserei_Zürich_Generator_Log_2025.csv",
  period_start: "2025-01-01",
  period_end: "2025-12-31",
  facility_id: null,
  facility_name: null,
  processing_status: "completed",
  detected_type: "Stationary fuel consumption record",
  also_in: [],
  values: 3,
  accepted: 0,
  flags: [],
  ...over,
});
const counts = { documents: 1, values: 3, accepted: 0, to_review: 3, issues: 0, pct_accepted: 0 };
const treeWith = (row: TreeDocRow): TreeData =>
  ({
    blocks: {
      summary: [],
      unassigned: [],
      supporting: { scopes: [], unassigned: [row], unassigned_counts: counts },
    },
    facilities: [{ facility_id: "fac-zh", name: "Käserei Zürich Nord" }],
    lines: [],
    set_aside: [],
  }) as unknown as TreeData;
const SUGGESTION = { facility_id: "fac-zh", facility_name: "Käserei Zürich Nord", quote: "Käserei_Zürich", where: "the file name", label: "Suggested by Claude" };
const ENGAGEMENT: EngagementConfig = { ...engagementConfig, engagementId: ENG, facilities: [{ facilityId: "fac-zh", name: "Käserei Zürich Nord" }], evidenceLines: [] };

function Tree({ onPlace }: { onPlace?: (documentId: string, facilityId: string) => Promise<void> }) {
  return (
    <EvidenceTree
      engagement={ENGAGEMENT}
      reloadKey="a"
      facilityId={null}
      onFacilityChange={vi.fn()}
      openIds={["b:supporting-unassigned", "b:supporting"]}
      onOpenIdsChange={vi.fn()}
      onOpenExtraction={vi.fn()}
      onOpenSchedule={vi.fn()}
      onMovePlacement={vi.fn().mockResolvedValue(undefined)}
      onPlaceOnFacility={onPlace}
      onCreateLine={vi.fn().mockResolvedValue(undefined)}
      onRenameLine={vi.fn().mockResolvedValue(undefined)}
      onDeleteLine={vi.fn().mockResolvedValue(0)}
      writesEnabled
    />
  );
}

beforeEach(() => {
  mocks.calls = [];
});

describe("Claude's facility suggestion on the Evidence tree row", () => {
  it("shows who suggested it, the quote and where, with a one-click Place on <facility>", async () => {
    mocks.tree = treeWith(doc({ facility_suggestion: SUGGESTION }));
    const onPlace = vi.fn().mockResolvedValue(undefined);
    render(<Tree onPlace={onPlace} />);
    const note = await screen.findByTestId("ai-facility-note");
    expect(note).toHaveTextContent("Facility suggested by Claude");
    expect(note).toHaveTextContent("“Käserei_Zürich” · the file name");
    fireEvent.click(screen.getByRole("button", { name: "Place on Käserei Zürich Nord" }));
    await waitFor(() => expect(onPlace).toHaveBeenCalledWith("LOG", "fac-zh"));
  });

  it("shows nothing when the row has no suggestion", async () => {
    mocks.tree = treeWith(doc());
    render(<Tree onPlace={vi.fn()} />);
    await screen.findByText("Käserei_Zürich_Generator_Log_2025.csv");
    expect(screen.queryByTestId("ai-facility-note")).toBeNull();
  });

  it("says in words when the placement did not save, and keeps the suggestion", async () => {
    mocks.tree = treeWith(doc({ facility_suggestion: SUGGESTION }));
    render(<Tree onPlace={vi.fn().mockRejectedValue(new Error("Try again in a moment."))} />);
    fireEvent.click(await screen.findByRole("button", { name: "Place on Käserei Zürich Nord" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't place the document.");
    expect(screen.getByTestId("ai-facility-note")).toBeInTheDocument();
  });

  it("cannot be clicked by a reader (no write access)", async () => {
    mocks.tree = treeWith(doc({ facility_suggestion: SUGGESTION }));
    render(<Tree />);
    expect(await screen.findByRole("button", { name: "Place on Käserei Zürich Nord" })).toBeDisabled();
  });
});

describe("Claude's facility suggestion on the review screen", () => {
  const item = (suggestion: boolean) =>
    ({
      documentId: manufacturerValues[0].documentId, filename: "Käserei_Zürich_Generator_Log_2025.csv", facilityState: "unresolved", facilityId: null, facilityName: null,
      disposition: "active", relationships: [], detectedType: "Stationary fuel consumption record",
      ...(suggestion ? { facilitySuggestion: { facilityId: "fac-zh", quote: "Käserei_Zürich", where: "the file name" } } : {}),
    }) as never;
  const review = (typeItem: never, onPlace?: (documentId: string, facilityId: string) => Promise<void>) => (
    <ExtractionReview
      engagement={ENGAGEMENT}
      values={manufacturerValues}
      onValuesChange={vi.fn()}
      initialDocumentId={manufacturerValues[0].documentId}
      initialDocumentName="Käserei_Zürich_Generator_Log_2025.csv"
      typeItem={typeItem}
      onPlaceOnFacility={onPlace}
      onSaveAsk={vi.fn()}
      onBack={vi.fn()}
    />
  );

  it("shows the suggestion with the same words and places the document on a click", async () => {
    const onPlace = vi.fn().mockResolvedValue(undefined);
    render(review(item(true), onPlace));
    expect(await screen.findByTestId("ai-facility-note")).toHaveTextContent("“Käserei_Zürich” · the file name");
    fireEvent.click(screen.getByRole("button", { name: "Place on Käserei Zürich Nord" }));
    await waitFor(() => expect(onPlace).toHaveBeenCalledWith(manufacturerValues[0].documentId, "fac-zh"));
  });

  it("shows nothing when there is no suggestion", () => {
    render(review(item(false), vi.fn()));
    expect(screen.queryByTestId("ai-facility-note")).toBeNull();
  });
});

describe("the shared note", () => {
  it("is the same words on the review screen", () => {
    const onPlace = vi.fn();
    render(<AiFacilityNote facilityName="Fresno Plant" quote="Fresno" where="page 2" onPlace={onPlace} />);
    expect(screen.getByTestId("ai-facility-note")).toHaveTextContent("Facility suggested by Claude");
    fireEvent.click(screen.getByRole("button", { name: "Place on Fresno Plant" }));
    expect(onPlace).toHaveBeenCalledTimes(1);
  });
});

describe("the Activity log", () => {
  const base = { evidence: [], values: [], asks: [], findings: [] };
  it("says the reviewer placed the document, and that it was Claude's suggestion", () => {
    const log = engagementActivity({
      ...base,
      evidence: [{ documentId: "LOG", filename: "Käserei_Zürich_Generator_Log_2025.csv", uploadedAt: "2025-01-01T00:00:00Z", uploadedBy: { name: "Ana" } }] as never,
      evidenceEvents: [
        { id: "1", at: "2025-11-04T12:00:00Z", actor_name: "Jane Park", event_type: "evidence_document_facility_set", document_id: "LOG", facility_id: "fac-zh", facility_name: "Käserei Zürich Nord", suggested: true },
        { id: "2", at: "2025-11-04T12:01:00Z", actor_name: "Jane Park", event_type: "evidence_document_facility_set", document_id: "LOG", facility_id: "fac-zh", facility_name: "Käserei Zürich Nord", suggested: false },
      ],
    });
    const placed = log.filter((e) => e.what.startsWith("placed"));
    expect(placed.map((e) => e.what)).toEqual([
      "placed Käserei_Zürich_Generator_Log_2025.csv on Käserei Zürich Nord",
      "placed Käserei_Zürich_Generator_Log_2025.csv on Käserei Zürich Nord, as Claude suggested",
    ]);
    expect(placed[1].who).toBe("Jane Park");
  });
});

describe("demo backend: place on a facility", () => {
  beforeAll(() => {
    vi.stubEnv("NEXT_PUBLIC_S1_DATA_MODE", "fixture");
    setDemoEngagement({ ...engagementConfig, evidenceLines: [] });
  });
  afterAll(() => {
    vi.unstubAllEnvs();
  });

  it("saves the reviewer's decision, logs it, and refuses a facility that is not in Setup", async () => {
    const id = engagementConfig.engagementId;
    const tree = await demoApi<TreeData>(`/engagements/${id}/evidence-tree`);
    const first = [...tree.blocks.unassigned, ...tree.blocks.supporting.unassigned][0] ??
      tree.blocks.supporting.scopes.flatMap((s) => s.categories.flatMap((c) => c.level2s.flatMap((l) => l.lines.flatMap((n) => n.documents))))[0];
    const facility = engagementConfig.facilities[0];
    const saved = await demoApi<{ payload: { facilityId?: string } }>(`/engagements/${id}/documents/${first.document_id}/facility`, {
      method: "POST",
      body: { facility_id: facility.facilityId },
    });
    expect(saved.payload.facilityId).toBe(facility.facilityId);
    const log = await demoApi<{ items: { event_type: string; facility_name?: string }[] }>(`/engagements/${id}/evidence-activity`);
    expect(log.items[0]).toMatchObject({ event_type: "evidence_document_facility_set", facility_name: facility.name });
    await expect(
      demoApi(`/engagements/${id}/documents/${first.document_id}/facility`, { method: "POST", body: { facility_id: "nope" } })
    ).rejects.toMatchObject({ status: 422 });
  });

  it("is safe to repeat and refuses a stale click", async () => {
    const id = engagementConfig.engagementId;
    const tree = await demoApi<TreeData>(`/engagements/${id}/evidence-tree`);
    const docs = tree.blocks.supporting.scopes.flatMap((s) => s.categories.flatMap((c) => c.level2s.flatMap((l) => l.lines.flatMap((n) => n.documents))));
    const target = docs[docs.length - 1];
    const [a, b] = engagementConfig.facilities;
    const post = (facility: string, expected?: string | null) =>
      demoApi<{ payload: { facilityId?: string } }>(`/engagements/${id}/documents/${target.document_id}/facility`, {
        method: "POST",
        body: expected === undefined ? { facility_id: facility } : { facility_id: facility, expected_facility_id: expected },
      });
    const events = async () =>
      (await demoApi<{ items: { event_type: string }[] }>(`/engagements/${id}/evidence-activity`)).items.filter((e) => e.event_type === "evidence_document_facility_set").length;
    const before = await events();
    await post(a.facilityId, null);
    await post(a.facilityId, null); // the repeat writes and logs nothing
    expect(await events()).toBe(before + 1);
    await expect(post(b.facilityId, null)).rejects.toMatchObject({ status: 409 }); // this page believed there was no choice
    expect((await post(b.facilityId, a.facilityId)).payload.facilityId).toBe(b.facilityId);
  });

  it("sends the facility the page believes the document is on, so the server can refuse a stale click", async () => {
    mocks.calls = [];
    await setDocumentFacility("eng-1", "LOG", "fac-zh", null);
    await setDocumentFacility("eng-1", "LOG2", "fac-zh", "fac-old");
    expect(mocks.calls.map((c) => c.options?.body)).toEqual([
      { facility_id: "fac-zh", expected_facility_id: null },
      { facility_id: "fac-zh", expected_facility_id: "fac-old" },
    ]);
  });
});

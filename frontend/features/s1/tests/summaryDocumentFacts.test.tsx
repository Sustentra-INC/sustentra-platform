/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mock = vi.hoisted(() => ({ review: null as unknown, locations: [] as unknown[] }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn((path: string, options?: { method?: string }) => {
    if (options?.method) return Promise.resolve({});
    return Promise.resolve(path.endsWith("/locations") ? { items: mock.locations } : mock.review);
  }),
}));

import { api } from "../../../lib/api";
import { BackendMethodologyReview } from "../components/BackendMethodologyReview";
import { SummaryDocumentReview, WithMethodologyFacts, type MethodologyFacts, type SummaryViewerProps } from "../components/SummaryDocumentReview";
import { parseViewFromSearch, viewToSearch } from "../utils/viewHistory";

afterEach(cleanup);

const BASE = "/engagements/e1/methodology-review";
const by = { name: "M. Osei", login: "mosei" };
const ref = (page: number) => ({ page_number: page });
const sug = (value: string, quote: string, page: number) => ({
  value,
  quote,
  document_id: "d1",
  file_name: "GHG statement.pdf",
  source_reference: ref(page),
  origin: "ai",
  model: "m",
  request_id: "r",
  suggested_at: "2026-11-01T10:00:00Z",
});

function review(decided = false) {
  const def = { group_label: "x", user_added: false };
  return {
    ai: { enabled: true, reason_code: null, reason: null },
    groups: [
      { group: "boundary", label: "Organizational boundary" },
      { group: "gases", label: "Gases covered" },
    ],
    row_groups: [],
    catalog: [
      { ...def, field_id: "consolidation_approach", group: "boundary", label: "Consolidation approach", kind: "enum", allowed: ["Equity Share", "Operational Control"] },
      { ...def, field_id: "gas:co2", group: "gases", label: "Gas: CO2", kind: "enum", allowed: ["Yes", "No"], required: false },
      { ...def, field_id: "gas:ch4", group: "gases", label: "Gas: CH4", kind: "enum", allowed: ["Yes", "No"], required: false },
    ],
    fields: [
      { field_id: "consolidation_approach", user_added: false, suggestion: sug("Operational Control", "We use the operational control approach.", 2), decision: null, history: [] },
      {
        field_id: "gas:co2",
        user_added: false,
        suggestion: sug("Yes", "Carbon dioxide (CO2) is reported.", 5),
        decision: decided ? { status: "accepted", value: "Yes", by, at: "2026-11-02T10:00:00Z" } : null,
        history: [],
      },
      { field_id: "gas:ch4", user_added: false, suggestion: sug("Yes", "Methane (CH4) is reported.", 5), decision: null, history: [] },
    ],
  };
}

const loc = (fieldId: string, page: number, located: boolean) => ({
  field_id: fieldId,
  entry: null,
  page,
  located,
  rects: located ? [{ x: 0.1, y: 0.2, w: 0.4, h: 0.02 }] : [],
});

let latest: SummaryViewerProps | null = null;
function viewer(props: SummaryViewerProps): ReactNode {
  latest = props;
  return (
    <div data-testid="viewer" data-page={props.page ?? ""}>
      <span data-testid="marks">{props.marks.map((m) => `${m.id}@p${m.span?.page}:${m.reviewState}`).join(",")}</span>
      <span data-testid="selected">{props.selectedMarkIds.join(",")}</span>
      {props.pageNote ? <p role="status">{props.pageNote}</p> : null}
    </div>
  );
}

function open(at?: { fieldId?: string; entry?: number; page?: number }, onBack = vi.fn()) {
  render(
    <SummaryDocumentReview engagementId="e1" documentId="d1" fileName="GHG statement.pdf" at={at} backLabel="methodology" onBack={onBack} renderViewer={viewer} />
  );
  return { onBack };
}

beforeEach(() => {
  vi.mocked(api).mockClear();
  mock.review = review();
  mock.locations = [loc("consolidation_approach", 2, true), loc("gas:co2", 5, true), loc("gas:ch4", 5, false)];
  latest = null;
});

describe("a methodology source link opens the document at its page with the quote", () => {
  it("each source link on Methodology review hands over the field and the cited page 5 for the gases rows", () => {
    // (the page 5 links are checked on the real Methodology screen below)
    expect(parseViewFromSearch(viewToSearch({ name: "extraction", documentId: "d1", mode: "snippet", field: "gas:co2", page: 5 }, "e1"))).toEqual({
      name: "extraction",
      documentId: "d1",
      mode: "snippet",
      nodeKey: undefined,
      valueId: undefined,
      page: 5,
      field: "gas:co2",
    });
    expect(viewToSearch({ name: "extraction", documentId: "d1", field: "gas:co2", entry: 0, page: 5 }, "e1")).toContain("page=5");
    expect(parseViewFromSearch("?view=review&doc=d1&page=0&field=gas%3Aco2&entry=x")).toMatchObject({ field: "gas:co2" });
    expect(parseViewFromSearch("?view=review&doc=d1&page=abc")).not.toHaveProperty("page");
  });

  it("the gases rows' source links on Methodology review say the field, no list entry, and page 5", async () => {
    mock.review = review();
    const onOpenDocument = vi.fn();
    render(<BackendMethodologyReview engagementId="e1" onOpenDocument={onOpenDocument} />);
    await screen.findByText("CO₂");
    const co2 = screen.getByText("CO₂").closest("tbody") as HTMLElement;
    fireEvent.click(co2.querySelector("button.s1-mr-link") as HTMLElement);
    expect(onOpenDocument).toHaveBeenCalledWith("d1", { fieldId: "gas:co2", entry: null, page: 5 });
    const ch4 = screen.getByText("CH₄").closest("tbody") as HTMLElement;
    fireEvent.click(ch4.querySelector("button.s1-mr-link") as HTMLElement);
    expect(onOpenDocument).toHaveBeenLastCalledWith("d1", { fieldId: "gas:ch4", entry: null, page: 5 });
  });

  it("opens at page 5 with the quote highlighted and selected", async () => {
    open({ fieldId: "gas:co2", page: 5 });
    await screen.findByText("Gas: CO2");
    expect(screen.getByTestId("viewer")).toHaveAttribute("data-page", "5");
    expect(screen.getByTestId("selected")).toHaveTextContent("gas:co2##0");
    expect(screen.getByTestId("marks")).toHaveTextContent("gas:co2##0@p5:to_review");
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByText("Gas: CO2").closest("li")).toHaveAttribute("data-selected", "true");
  });

  it("a quote that cannot be located still opens page 5 and says so, with no highlight for it", async () => {
    open({ fieldId: "gas:ch4", page: 5 });
    await screen.findByText("Gas: CH4");
    expect(screen.getByTestId("viewer")).toHaveAttribute("data-page", "5");
    expect(screen.getByRole("status")).toHaveTextContent("Quote not located on this page");
    expect(screen.getByTestId("selected")).toHaveTextContent("");
    expect(screen.getByTestId("marks")).not.toHaveTextContent("gas:ch4");
    // the value itself is still listed, flagged on its own row
    expect(screen.getByText("Quote not located on page 5")).toBeInTheDocument();
  });

  it("Back returns to where the user came from", async () => {
    const { onBack } = open({ fieldId: "gas:co2", page: 5 });
    await screen.findByText("Gas: CO2");
    fireEvent.click(screen.getByRole("button", { name: /Back to methodology/ }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});

describe("the facts are the Methodology review decisions", () => {
  it("lists the document's facts grouped as Methodology review groups them, with highlights by state", async () => {
    mock.review = review(true);
    open();
    await screen.findByText("Gas: CO2");
    expect(screen.getByText("Organizational boundary")).toBeInTheDocument();
    expect(screen.getByText("Gases covered")).toBeInTheDocument();
    expect(screen.getByTestId("marks")).toHaveTextContent("gas:co2##0@p5:accepted");
    expect(screen.getByTestId("marks")).toHaveTextContent("consolidation_approach##0@p2:to_review");
  });

  it("Accept calls the Methodology review endpoint for that field and reloads it", async () => {
    open();
    await screen.findByText("Gas: CO2");
    fireEvent.click(screen.getByRole("button", { name: "Accept: Gas: CO2" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith(`${BASE}/gas%3Aco2/accept`, { method: "POST", body: {} }));
    await waitFor(() => expect(vi.mocked(api).mock.calls.filter(([p]) => p === BASE).length).toBeGreaterThan(1));
  });

  it("clicking a highlight selects its row; clicking a row moves the highlight", async () => {
    open();
    await screen.findByText("Gas: CO2");
    fireEvent.click(screen.getByText("Consolidation approach").closest("li") as HTMLElement);
    expect(screen.getByTestId("selected")).toHaveTextContent("consolidation_approach##0");
    expect(screen.getByTestId("viewer")).toHaveAttribute("data-page", "2");
    latest?.onPickMark(latest.marks.find((m) => m.id.startsWith("gas:co2")) as never);
    await waitFor(() => expect(screen.getByTestId("selected")).toHaveTextContent("gas:co2##0"));
    expect(screen.getByTestId("viewer")).toHaveAttribute("data-page", "5");
  });

  it("with nothing read yet it offers Read with Sustentra's AI, which calls the Methodology prefill", async () => {
    mock.locations = [];
    open();
    fireEvent.click(await screen.findByRole("button", { name: "Read with Sustentra's AI" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith(`${BASE}/prefill`, { method: "POST", body: {} }));
  });
});

describe("the page uses the same layout as every other document's review", () => {
  it("is the extraction grid: navigator, the document, then the facts panel in the right-hand slot", async () => {
    open({ fieldId: "gas:co2", page: 5 });
    await screen.findByText("Gas: CO2");
    const grid = document.querySelector(".s1-xr-grid") as HTMLElement;
    expect(grid).not.toBeNull();
    const [nav, source, values] = Array.from(grid.children) as HTMLElement[];
    expect(nav).toHaveClass("s1-xr-nav");
    expect(source).toHaveClass("s1-xr-source");
    expect(values).toHaveClass("s1-xr-values");
    expect(source.contains(screen.getByTestId("viewer"))).toBe(true);
    expect(values.contains(screen.getByText("Gas: CO2"))).toBe(true);
    expect(source.compareDocumentPosition(values) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(grid.querySelector(".s1-sd")).toBeNull();
  });
});

describe("the facts beside a document that also has reported figures", () => {
  it("are read before the page opens, so a deep link to page 5 selects its quote", async () => {
    const seen: (MethodologyFacts | undefined)[] = [];
    render(
      <WithMethodologyFacts engagementId="e1" documentId="d1" at={{ fieldId: "gas:co2", page: 5 }}>
        {(facts) => {
          seen.push(facts);
          return <div data-testid="page">{facts ? facts.selectedMarkIds.join(",") : "no facts"}</div>;
        }}
      </WithMethodologyFacts>
    );
    expect(screen.queryByTestId("page")).toBeNull();
    await screen.findByTestId("page");
    expect(screen.getByTestId("page")).toHaveTextContent("gas:co2##0");
    expect(seen.every((f) => f !== undefined)).toBe(true);
    expect(seen[0]?.page).toBe(5);
    expect(seen[0]?.count).toBe(3);
  });
});

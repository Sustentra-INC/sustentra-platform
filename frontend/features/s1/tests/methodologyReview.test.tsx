/* @vitest-environment jsdom */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useEffect, useState } from "react";
import { describe, expect, it } from "vitest";

import { MethodologyReview } from "../components/MethodologyReview";
import { S1Chrome } from "../components/S1Chrome";
import { engagementConfig } from "../fixtures/engagementConfig";
import { emptyMethodologyReview, methodologyStated } from "../fixtures/methodology/methodologyReview";
import type { MethodologyState } from "../types/methodology";
import { engagementActivity } from "../utils/engagementActivity";

let latest: MethodologyState = emptyMethodologyReview();
function record(review: MethodologyState) {
  latest = review;
}

function Harness() {
  const [review, setReview] = useState<MethodologyState>(emptyMethodologyReview);
  useEffect(() => record(review), [review]);
  return <MethodologyReview stated={methodologyStated} review={review} onChange={setReview} verifier="M. Osei" />;
}

const groupHead = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name}`) });
const entityRow = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name}`) }).closest("tr") as HTMLElement;

describe("Methodology review", () => {
  it("folds each group from its header, which shows only a red flag count", () => {
    render(<Harness />);
    const factors = groupHead("Emission factors source");
    expect(factors.textContent).toBe("Emission factors source1 flag");
    expect(groupHead("Scope 1 emission categories").textContent).toBe("Scope 1 emission categories");

    const s1 = groupHead("Scope 1 emission categories");
    expect(s1.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("combobox", { name: "Included: Stationary Combustion" })).toBeTruthy();
    fireEvent.click(s1);
    expect(s1.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("combobox", { name: "Included: Stationary Combustion" })).toBeNull();
  });

  it("switches the boundary approach: Yes/No under operational control, a share otherwise", () => {
    render(<Harness />);
    const approach = screen.getByRole("combobox", { name: "Organizational boundary approach" }) as HTMLSelectElement;
    expect(approach.value).toBe("Operational Control");
    const entityHeads = () => Array.from(document.querySelectorAll(".s1-mr-entities th")).map((th) => th.textContent);
    expect(entityHeads()).toEqual(["Entity", "Included", "Review · 0 of 3"]);
    expect((screen.getByRole("combobox", { name: "Included: Stockton Cold Storage JV" }) as HTMLSelectElement).value).toBe("No");
    expect(within(entityRow("Stockton Cold Storage JV")).getByText("Not operated by Cascade Provisions")).toBeTruthy();

    fireEvent.change(approach, { target: { value: "Equity Share" } });
    expect(entityHeads()[1]).toBe("Equity share");
    expect((screen.getByRole("spinbutton", { name: "Equity share for Stockton Cold Storage JV" }) as HTMLInputElement).value).toBe("50");
    expect(screen.getByText(/^Adjusted by verifier M\. Osei · /)).toBeTruthy();

    fireEvent.change(approach, { target: { value: "Financial Control" } });
    expect(entityHeads()[1]).toBe("Consolidated share");
    expect(screen.getByText("Joint financial control: equity share applies")).toBeTruthy();

    const revert = screen.getByRole("button", { name: "Revert" });
    expect(revert.getAttribute("title")).toBe("Revert to: Operational Control");
    fireEvent.click(revert);
    expect(approach.value).toBe("Operational Control");
    expect(screen.queryByText(/^Adjusted by verifier/)).toBeNull();
  });

  it("accepts an entity, shows a correction, and resets it when the value changes again", () => {
    render(<Harness />);
    expect(screen.getByRole("columnheader", { name: "Review · 0 of 3" })).toBeTruthy();

    fireEvent.click(within(entityRow("Cascade Provisions Co.")).getByRole("button", { name: "Accept" }));
    expect(within(entityRow("Cascade Provisions Co.")).getByText("Accepted")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Review · 1 of 3" })).toBeTruthy();

    const stockton = screen.getByRole("combobox", { name: "Included: Stockton Cold Storage JV" });
    fireEvent.change(stockton, { target: { value: "Yes" } });
    fireEvent.click(within(entityRow("Stockton Cold Storage JV")).getByRole("button", { name: "Accept" }));
    expect(within(entityRow("Stockton Cold Storage JV")).getByText("Corrected from No")).toBeTruthy();

    // Changing the value again sends the row back to Accept.
    fireEvent.change(stockton, { target: { value: "No" } });
    expect(within(entityRow("Stockton Cold Storage JV")).getByRole("button", { name: "Accept" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Review · 1 of 3" })).toBeTruthy();

    // An entity opens to its facilities, each inheriting the entity's share.
    fireEvent.click(screen.getByRole("button", { name: /^Cascade Provisions Co\./ }));
    const kent = screen.getByText("Kent Cannery").closest("tr") as HTMLElement;
    expect(within(kent).getByText("Inherits 100%")).toBeTruthy();
    expect(screen.getByText("Modesto Bottling")).toBeTruthy();

    expect(latest.log.map((l) => l.what)).toEqual([
      "accepted Cascade Provisions Co. (Included: Yes)",
      "corrected Stockton Cold Storage JV from No to Yes",
    ]);
  });

  it("marks a changed category with who and when, and reverts it", () => {
    render(<Harness />);
    const process = screen.getByRole("combobox", { name: "Included: Process Emissions" }) as HTMLSelectElement;
    fireEvent.change(process, { target: { value: "Yes" } });
    const row = process.closest("tr") as HTMLElement;
    expect(within(row).getByText(/^Adjusted by verifier M\. Osei · /)).toBeTruthy();
    fireEvent.click(within(row).getByRole("button", { name: "Revert" }));
    expect(process.value).toBe("Not detected");
    expect(within(row).queryByText(/Adjusted/)).toBeNull();

    // Scope 2: the line goes under the row.
    const cooling = screen.getByRole("combobox", { name: "Market-Based, included: Purchased Cooling" });
    fireEvent.change(cooling, { target: { value: "No" } });
    expect((cooling.closest("tr")!.nextElementSibling as HTMLElement).textContent?.trim()).toMatch(/^Adjusted by verifier M\. Osei · .*Revert$/);
  });

  it("edits a stated text through Edit, then Save or Cancel, and drops its citation once changed", () => {
    render(<Harness />);
    const row = screen.getByText("Excluded from this inventory").closest(".s1-mr-textrow") as HTMLElement;
    expect(within(row).getByText("GHG Report p. 5")).toBeTruthy();

    fireEvent.click(within(row).getByRole("button", { name: "Edit excluded from this inventory" }));
    fireEvent.change(within(row).getByRole("textbox"), { target: { value: "Nothing else" } });
    fireEvent.click(within(row).getByRole("button", { name: "Cancel" }));
    expect(within(row).queryByText("Nothing else")).toBeNull();

    fireEvent.click(within(row).getByRole("button", { name: "Edit excluded from this inventory" }));
    fireEvent.change(within(row).getByRole("textbox"), { target: { value: "Backup diesel generators at Tualatin Plant." } });
    fireEvent.click(within(row).getByRole("button", { name: "Save" }));
    expect(within(row).getByText("Backup diesel generators at Tualatin Plant.")).toBeTruthy();
    expect(within(row).queryByText("GHG Report p. 5")).toBeNull();
    expect(within(row).getByText(/^Adjusted by verifier M\. Osei · /)).toBeTruthy();

    fireEvent.click(within(row).getByRole("button", { name: "Revert" }));
    expect(within(row).getByText("GHG Report p. 5")).toBeTruthy();

    // The reporting period edits the same way, on one line.
    fireEvent.click(screen.getByRole("button", { name: "Edit reporting period" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Reporting period" }), { target: { value: "2025-01-01 to 2025-06-30" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("2025-01-01 to 2025-06-30")).toBeTruthy();
  });

  it("resolves the eGRID mismatch by saving either row: the other hides and the flag clears", () => {
    render(<Harness />);
    const stated = screen.getByText("eGRID2023").closest("tr") as HTMLElement;
    expect(within(stated).getByText("Mismatch")).toBeTruthy();

    fireEvent.click(within(screen.getByText("eGRID2021").closest("tr") as HTMLElement).getByRole("button", { name: "Edit EPA eGRID eGRID2021" }));
    const editor = screen.getByRole("textbox", { name: "Edition" }).closest("tr") as HTMLElement;
    expect(within(editor).getByText("Set by verifier on save")).toBeTruthy();
    fireEvent.change(within(editor).getByRole("textbox", { name: "Edition" }), { target: { value: "eGRID2023" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Save" }));

    expect(screen.queryByText("eGRID2021")).toBeNull();
    expect(screen.getAllByText("eGRID2023")).toHaveLength(1);
    const set = screen.getByText("eGRID2023").closest("tr") as HTMLElement;
    expect(within(set).getByText("Set by verifier")).toBeTruthy();
    expect(within(set).queryByText("Mismatch")).toBeNull();
    expect(groupHead("Emission factors source").textContent).toBe("Emission factors source");
    expect(screen.queryByText(/^Adjusted by verifier/)).toBeNull();

    // Revert restores the stated row and the mismatch it resolved.
    fireEvent.click(within(set).getByRole("button", { name: "Revert" }));
    expect(screen.getByText("eGRID2021")).toBeTruthy();
    expect(screen.getAllByText("Mismatch")).toHaveLength(2);
    expect(groupHead("Emission factors source").textContent).toBe("Emission factors source1 flag");
  });

  it("adds a source the verifier sets, and removes it", () => {
    render(<Harness />);
    const scope1 = screen.getAllByRole("button", { name: /Add source/ })[0];
    fireEvent.click(scope1);
    const editor = screen.getByRole("textbox", { name: "Database" }).closest("tr") as HTMLElement;
    expect(within(editor).getByRole("button", { name: "Save" })).toHaveProperty("disabled", true);
    fireEvent.change(within(editor).getByRole("textbox", { name: "Database" }), { target: { value: "DEFRA conversion factors" } });
    fireEvent.change(within(editor).getByRole("textbox", { name: "Edition" }), { target: { value: "2025" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Save" }));
    const added = screen.getByText("DEFRA conversion factors").closest("tr") as HTMLElement;
    expect(within(added).getByText("Set by verifier")).toBeTruthy();
    fireEvent.click(within(added).getByRole("button", { name: "Remove" }));
    expect(screen.queryByText("DEFRA conversion factors")).toBeNull();
  });

  it("edits the GWP set and time horizon; a horizon other than 100-year is flagged", () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Edit GWP set" }));
    fireEvent.change(screen.getByRole("combobox", { name: "GWP set" }), { target: { value: "IPCC Sixth Assessment Report (AR6)" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Time horizon" }), { target: { value: "20-year" } });
    fireEvent.click(within(screen.getByRole("combobox", { name: "Time horizon" }).closest("tr") as HTMLElement).getByRole("button", { name: "Save" }));

    const row = screen.getByText("IPCC Sixth Assessment Report (AR6)").closest("tr") as HTMLElement;
    expect(within(row).getByText("Set by verifier")).toBeTruthy();
    expect(within(row).getByText("Not 100-year")).toBeTruthy();
    expect(groupHead("GWP factors source").textContent).toBe("GWP factors source1 flag");

    fireEvent.click(within(row).getByRole("button", { name: "Revert" }));
    expect(screen.getByText("IPCC Fifth Assessment Report (AR5)")).toBeTruthy();
    expect(groupHead("GWP factors source").textContent).toBe("GWP factors source");
  });

  it("writes every change to the activity log", () => {
    render(<Harness />);
    fireEvent.change(screen.getByRole("combobox", { name: "Organizational boundary approach" }), { target: { value: "Equity Share" } });
    const entries = engagementActivity({ evidence: [], values: [], asks: [], findings: [], methodology: latest.log });
    expect(entries).toEqual([
      expect.objectContaining({
        who: "M. Osei",
        what: "changed the boundary approach from Operational Control to Equity Share",
        kind: "methodology",
      }),
    ]);
  });

  it("sits in the sidebar between Coverage & requests and Verification results, on the demo only", () => {
    const nav = () =>
      within(screen.getByRole("navigation", { name: "Primary" }))
        .getAllByRole("button")
        .map((b) => b.textContent);
    const { rerender } = render(
      <S1Chrome engagement={engagementConfig}>
        <div />
      </S1Chrome>
    );
    const order = nav();
    expect(order.slice(order.indexOf("Coverage & requests"), order.indexOf("Coverage & requests") + 3)).toEqual([
      "Coverage & requests",
      "Methodology review",
      "Verification results",
    ]);
    rerender(
      <S1Chrome engagement={engagementConfig} hiddenNav={["methodology"]}>
        <div />
      </S1Chrome>
    );
    expect(nav()).not.toContain("Methodology review");
  });
});

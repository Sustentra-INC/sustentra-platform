import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  AskCard,
  CalculationStrip,
  ChangeItem,
  ContainerState,
  CoverageGrid,
  DocumentRow,
  ExaminationRecord,
  FindingRow,
  InventoryLineRow,
  PersonSlot,
  ProcedureRow,
  StateChip,
  TechniqueSelector,
  ProgressBar,
  RequestRow,
  RequirementRow,
  type S2ContainerStateValue,
} from "../components";
import { CONTAINER, REFUSALS, TECHNIQUES_LIMITED } from "../constants/copy";

describe("S2 Wave 1 components", () => {
  it("exports the named S2 component inventory", () => {
    const namedComponents = [
      AskCard,
      CalculationStrip,
      ChangeItem,
      ContainerState,
      CoverageGrid,
      DocumentRow,
      ExaminationRecord,
      FindingRow,
      InventoryLineRow,
      PersonSlot,
      ProcedureRow,
      ProgressBar,
      RequestRow,
      RequirementRow,
      StateChip,
      TechniqueSelector,
    ];

    expect(namedComponents).toHaveLength(16);
    for (const Component of namedComponents) {
      expect(typeof Component).toBe("function");
    }
  });

  it("keeps TechniqueSelector as a named component", () => {
    expect(TechniqueSelector.name).toBe("TechniqueSelector");
    const html = renderToStaticMarkup(
      <TechniqueSelector selected={[]} onChange={() => undefined} />
    );

    expect(html).toContain("Record the examination");
    expect(html).toContain(TECHNIQUES_LIMITED[0]);
  });

  it("renders unknown state roles loudly", () => {
    const html = renderToStaticMarkup(
      <StateChip value="strange" role={"mystery" as never} />
    );

    expect(html).toContain("s2-unknown-value");
    expect(html).toContain("Unrecognised value: mystery");
  });

  it("supports the full 9-value S2 container-state contract", () => {
    const states: S2ContainerStateValue[] = [
      "populated",
      "emptyNothingReported",
      "emptyNothingExamined",
      "emptyFiltered",
      "loading",
      "error",
      "degraded",
      "blocked",
      "complete",
    ];

    expect(states).toHaveLength(9);
    for (const state of states) {
      const html = renderToStaticMarkup(
        <ContainerState state={state} detail={{ missing: ["Fleet", "Carson"], loaded: 6 }} />
      );
      if (state === "populated") {
        expect(html).toBe("");
      } else {
        expect(html).toContain("s2-container-state");
      }
    }
  });

  it("renders dependency-blocked copy as an engagement-level container state", () => {
    const html = renderToStaticMarkup(<ContainerState state="blocked" />);

    expect(html).toContain(CONTAINER.blocked);
    expect(html).toContain(CONTAINER.blockedHint);
  });

  it("refuses a no-exceptions record until a technique is selected", () => {
    const html = renderToStaticMarkup(
      <ExaminationRecord
        selected={[]}
        conclusion="noExceptions"
        assuranceLevel="limited"
        onChange={() => undefined}
        onRecord={() => undefined}
      />
    );

    expect(html).toContain(REFUSALS.noTechnique);
    expect(html).toContain("Record &amp; next");
  });

  it("displays performer and time as fixed record metadata", () => {
    const html = renderToStaticMarkup(
      <ExaminationRecord
        selected={["examination"]}
        assuranceLevel="limited"
        performedBy={{ id: "user-claire", name: "Claire Qiu" }}
        performedAt="Aug 8, 2026, 2:20 PM"
        onChange={() => undefined}
        onRecord={() => undefined}
      />
    );

    expect(html).toContain("Claire Qiu");
    expect(html).toContain("Aug 8, 2026, 2:20 PM");
    expect(html).not.toContain("value=\"Claire Qiu\"");
  });

  it("blocks reviewer assignment when reviewer equals performer", () => {
    const html = renderToStaticMarkup(
      <PersonSlot
        user={{ id: "user-claire", name: "Claire Qiu" }}
        label="Reviewed by"
        excludeUserIds={["user-claire"]}
        onChange={() => undefined}
      />
    );

    expect(html).toContain("disabled");
    expect(html).toContain(REFUSALS.reviewerSameAsPerformer);
  });

  it("renders CoverageGrid as one focusable grid with an active descendant", () => {
    const html = renderToStaticMarkup(
      <CoverageGrid
        axis={{ name: "Facility", values: ["Richmond", "Carson"] }}
        expected={4}
        heldCount={3}
        rows={[{ label: "Gas invoices", held: [true, false] }, { label: "Fuel analysis", held: [true, true] }]}
      />
    );

    expect(html).toContain("role=\"grid\"");
    expect(html).toContain("tabindex=\"0\"");
    expect(html).toContain("aria-activedescendant");
  });
});

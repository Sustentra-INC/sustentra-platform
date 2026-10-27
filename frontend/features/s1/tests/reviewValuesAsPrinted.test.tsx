/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";

import { encodeReviewCandidateToken, type BackendExtractionCandidateLike } from "../adapters/fieldAdapter";
import { reviewValuesFromFields } from "../adapters/reviewValueAdapter";
import { ExtractionReview } from "../components/ExtractionReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EvidenceItem, ExtractedField } from "../types";
import type { ReviewValue } from "../types/review";
import { formatDocumentPeriod, formatPrintedDate } from "../utils/formatPeriod";

/**
 * Staging's cards read the way the demo's do, as the document prints them: "182,400 kWh",
 * "01 Feb 2025", a group headed "Feb 2025". The value Accept and Correct record stays the one
 * the extraction normalised (182.4 MWh, 2025-02-01).
 */
describe("a document's dates as a person reads them", () => {
  it("heads a whole month, quarter or year by its name, and other spans by their days", () => {
    expect(formatDocumentPeriod("2025-02-01", "2025-02-28")).toBe("Feb 2025");
    expect(formatDocumentPeriod("2025-01-01", "2025-03-31")).toBe("Q1 2025");
    expect(formatDocumentPeriod("2025-01-01", "2025-12-31")).toBe("FY2025");
    expect(formatDocumentPeriod("2025-01-15", "2025-02-14")).toBe("15 Jan – 14 Feb 2025");
    expect(formatDocumentPeriod("2024-12-15", "2025-01-14")).toBe("15 Dec 2024 – 14 Jan 2025");
    expect(formatDocumentPeriod("2024-03-05", "2024-03-05")).toBe("05 Mar 2024");
    expect(formatDocumentPeriod("Feb 2025", "Mar 2025")).toBe("Feb 2025 – Mar 2025");
  });

  it("prints a date the way a bill does, and leaves anything else as read", () => {
    expect(formatPrintedDate("2025-02-01")).toBe("01 Feb 2025");
    expect(formatPrintedDate("2025-02-30")).toBe("2025-02-30");
    expect(formatPrintedDate("ACC-2231-77")).toBe("ACC-2231-77");
  });
});

const EV = "EV-1";
function candidate(
  name: string,
  raw: string | number | null,
  normalized: string | number | null,
  extra: Partial<BackendExtractionCandidateLike> = {},
  record = ""
): BackendExtractionCandidateLike {
  return {
    candidate_id: `candidate::${EV}::DOC-1::${name}${record}`, evidence_id: EV, document_id: "DOC-1", field_name: name,
    display_label: name, raw_value: raw, normalized_value: normalized, unit: null, ...extra,
  };
}
function field(c: BackendExtractionCandidateLike, extra: Partial<ExtractedField> = {}): ExtractedField {
  const value = c.normalized_value === null ? null : String(c.normalized_value);
  return {
    documentId: "DOC-1", canonicalTypeId: "CT-S2-ELEC", fieldKey: `candidate:${c.candidate_id}`,
    reviewToken: encodeReviewCandidateToken(c), fieldLabel: c.display_label, value, unit: c.unit,
    valueProperties: [], fieldState: value === null ? "missing_requestable" : "populated", snippet: null,
    snippetContext: null, location: null, reviewStatus: "unreviewed", correctedValue: null, valueOrigin: "extracted",
    ...extra,
  };
}
const DOC = { documentId: "DOC-1", filename: "kent_electric_feb_2025.pdf", format: "pdf", uploadedAt: "2026-10-20T09:00:00Z",
  detectedType: "Electricity bill" } as unknown as EvidenceItem;

const bill = () =>
  reviewValuesFromFields(
    [
      field(candidate("activity_quantity", "182,400", 182.4, { unit: "MWh", validation_flags: ["unit_converted"] })),
      field(candidate("activity_unit", "kWh", "MWh", { validation_flags: ["unit_converted"] })),
      field(candidate("service_period_start", "02/01/2025", "2025-02-01")),
      field(candidate("service_period_end", "02/28/2025", "2025-02-28")),
      field(candidate("account_number", "1234567", "1234567")),
    ],
    [DOC]
  );

describe("backend values as printed", () => {
  it("shows a converted quantity as read, with what the calculation uses kept as the value", () => {
    const [quantity, unit, start, , account] = bill();
    expect(quantity).toMatchObject({ value: "182.4", unit: "MWh", asPrinted: { value: "182,400", unit: "kWh", converted: true } });
    expect(unit).toMatchObject({ value: "MWh", asPrinted: { value: "kWh", unit: "", converted: true } });
    expect(start).toMatchObject({ value: "2025-02-01", asPrinted: { value: "01 Feb 2025", unit: "" } });
    // An account number is text, never a number to group.
    expect(account.asPrinted).toBeUndefined();
    expect(new Set(bill().map((v) => v.period))).toEqual(new Set(["Feb 2025"]));
  });

  it("groups the thousands of a quantity read as it is, and leaves a correction as typed", () => {
    const [litres, corrected, small] = reviewValuesFromFields(
      [
        field(candidate("activity_quantity", "1250.5", 1250.5, { unit: "gal" }, "::r1")),
        field(candidate("activity_quantity", "2400", 2400, { unit: "gal" }, "::r2"), { reviewStatus: "corrected", correctedValue: "2500" }),
        field(candidate("activity_quantity", "980", 980, { unit: "gal" }, "::r3")),
      ],
      [DOC]
    );
    expect(litres.asPrinted).toEqual({ value: "1,250.5", unit: "gal" });
    expect(corrected).toMatchObject({ value: "2500", asPrinted: undefined });
    expect(small.asPrinted).toBeUndefined();
  });

  it("takes each record's own printed unit on a log of several", () => {
    const values = reviewValuesFromFields(
      [
        field(candidate("activity_quantity", "41,200", 41.2, { unit: "MWh", validation_flags: ["unit_converted"] }, "::r1")),
        field(candidate("activity_unit", "kWh", "MWh", { validation_flags: ["unit_converted"] }, "::r1")),
        field(candidate("activity_quantity", "3", 3000, { unit: "MWh", validation_flags: ["unit_converted"] }, "::r2")),
        field(candidate("activity_unit", "GWh", "MWh", { validation_flags: ["unit_converted"] }, "::r2")),
      ],
      [DOC]
    );
    expect(values.filter((v) => v.unit === "MWh").map((v) => v.asPrinted)).toEqual([
      { value: "41,200", unit: "kWh", converted: true },
      { value: "3", unit: "GWh", converted: true },
    ]);
  });

  it("says which end of a period was not read", () => {
    const [only] = reviewValuesFromFields([field(candidate("service_period_start", "02/01/2025", "2025-02-01"))], [DOC]);
    expect(only.period).toBe("01 Feb 2025 – end not read");
  });
});

describe("a backend card as printed", () => {
  function renderBill(onPersistAccept = vi.fn(() => Promise.resolve())) {
    function Harness() {
      const [values, setValues] = useState<ReviewValue[]>(bill);
      return (
        <ExtractionReview
          engagement={engagementConfig}
          values={values}
          onValuesChange={setValues}
          initialDocumentId="DOC-1"
          initialValueId={values[0].id}
          onSaveAsk={vi.fn()}
          onBack={vi.fn()}
          onPersistAccept={onPersistAccept}
          onPersistCorrect={() => Promise.resolve()}
        />
      );
    }
    const { container } = render(<Harness />);
    const card = () => container.querySelector<HTMLElement>(".s1-xr-card.is-sel")!;
    return { container, card, onPersistAccept };
  }

  it("reads 182,400 kWh under a Feb 2025 header, and accepts the value recorded", () => {
    const { container, card, onPersistAccept } = renderBill();
    expect(container.querySelector(".s1-xr-doc")?.textContent).toContain("Feb 2025");
    expect(card().querySelector(".s1-xr-card__value")?.textContent).toBe("182,400kWh= 182.4 MWh, used in the calculation");
    fireEvent.click(within(card()).getByRole("button", { name: "Accept" }));
    expect(onPersistAccept).toHaveBeenCalledWith(expect.objectContaining({ value: "182.4", unit: "MWh" }));
  });

  it("corrects the recorded value and then shows the correction as typed", () => {
    const { container, card } = renderBill();
    fireEvent.click(within(card()).getByRole("button", { name: "Correct" }));
    expect(screen.getByLabelText("Value")).toHaveValue("182.4");
    expect(screen.getByLabelText("Unit")).toHaveValue("MWh");
    fireEvent.change(screen.getByLabelText("Value"), { target: { value: "182.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
    const corrected = container.querySelector<HTMLElement>(".s1-xr-card--corrected")!;
    expect(corrected.querySelector(".s1-xr-card__value")?.textContent).toBe("182.5MWhwas 182.4");
  });
});

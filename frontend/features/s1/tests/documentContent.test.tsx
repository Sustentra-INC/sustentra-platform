/* @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const content = vi.hoisted(() => ({ body: {} as unknown }));
vi.mock("../../../lib/api", () => ({
  api: vi.fn(() => Promise.resolve(content.body)),
  apiPath: (path: string) => `/api/v1${path}`,
}));

import { reviewValuesFromFields } from "../adapters/reviewValueAdapter";
import { encodeReviewCandidateToken } from "../adapters/fieldAdapter";
import { DocumentContentView } from "../components/DocumentContentView";
import { ExtractionReview } from "../components/ExtractionReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EvidenceItem, ExtractedField } from "../types";
import type { PageMark, ReviewValue } from "../types/review";
import { anchorOf, columnIndex, columnLetter, findInText, findTokens } from "../utils/sourceAnchor";

beforeAll(() => {
  Element.prototype.scrollIntoView = () => {}; // jsdom has no layout
});

describe("where a value sits in a file without pages", () => {
  it("reads the parsers' cell, row and line references", () => {
    expect(anchorOf("xlsx", { sheet_name: "2025 log", cell_or_range: "D2", parser_block_ids: ["openpyxl-2025 log-D2"] }))
      .toEqual({ kind: "cell", sheet: "2025 log", row: 2, column: 3 });
    expect(anchorOf("csv", { cell_or_range: "row 2", parser_block_ids: ["csv_parser-r2-b2"] })).toEqual({ kind: "row", row: 2 });
    expect(anchorOf("docx", { parser_block_ids: ["docx_parser-p1-b7", "docx_parser-p1-b6"] })).toEqual({ kind: "line", line: 7 });
    expect(anchorOf("other", { parser_block_ids: ["text_parser-p1-b3"] })).toEqual({ kind: "line", line: 3 });
    // An email (.eml) is its lines too: headers, message text, attachment names.
    expect(anchorOf("other", { cell_or_range: "part 2", parser_block_ids: ["email_parser-p1-b5"] }))
      .toEqual({ kind: "line", line: 5, part: 2 });
    expect(anchorOf("pdf", { parser_block_ids: ["pymupdf-p1-b3"] })).toBeNull(); // a PDF has its box
    expect(anchorOf("xlsx", { sheet_name: "Log", cell_or_range: null })).toBeNull();
  });

  it("converts column letters and finds a value's text in a line", () => {
    expect([columnIndex("A"), columnIndex("D"), columnIndex("AA")]).toEqual([0, 3, 26]);
    expect([columnLetter(0), columnLetter(25), columnLetter(26)]).toEqual(["A", "Z", "AA"]);
    const line = "Total kWh Used\t96,000 kWh";
    expect(findInText(line, "96,000")).toEqual([15, 21]);
    expect(findInText(line, "96000")).toEqual([15, 21]); // read as a number, shown with a comma
    expect(findInText(line, "KWH")).toEqual([6, 9]);
    expect(findInText(line, "120 therms")).toBeNull();
  });
});

const marks = (...items: [string, PageMark["anchor"], string][]): PageMark[] =>
  items.map(([id, anchor, rawText]) => ({ id, span: null, anchor, rawText, label: id, reviewState: "to_review" }));

describe("the file drawn with its values marked", () => {
  beforeEach(() => {
    content.body = {};
  });

  it("marks a Word value's words in its line and picks every value read there", async () => {
    content.body = { kind: "lines", truncated: false, lines: ["Keystone Gas & Electric", "Service Period\t01/01/2025 to 03/31/2025", "Total kWh Used\t96,000 kWh"] };
    const onPickAmong = vi.fn();
    render(
      <DocumentContentView
        documentId="DOC"
        selectedId="quantity"
        onPickAmong={onPickAmong}
        marks={marks(
          ["quantity", { kind: "line", line: 3 }, "96,000"],
          ["unit", { kind: "line", line: 3 }, "kWh"],
          ["start", { kind: "line", line: 2 }, "01/01/2025 to 03/31/2025"],
          ["end", { kind: "line", line: 2 }, "01/01/2025 to 03/31/2025"]
        )}
      />
    );
    const quantity = await screen.findByRole("button", { name: "Select quantity" });
    expect(quantity.textContent).toBe("96,000");
    expect(quantity.className).toContain("s1-cv__mark--selected");
    // The unit is the "kWh" after the amount, not the word in the label "Total kWh Used".
    const unit = screen.getByRole("button", { name: "Select unit" });
    expect(unit.textContent).toBe("kWh");
    expect(unit.parentElement?.textContent).toBe("Total kWh Used\t96,000 kWh");
    expect(unit.previousSibling?.textContent).toBe(" ");
    fireEvent.click(screen.getByRole("button", { name: "Select start · end" }));
    expect(onPickAmong).toHaveBeenCalledWith(["start", "end"]);
  });

  it("marks a workbook value in its cell, on its sheet", async () => {
    content.body = {
      kind: "sheets", truncated: false,
      sheets: [
        { name: "Notes", columns: 1, rows: [{ number: 1, cells: ["Read me"] }] },
        { name: "2025 log", columns: 4, rows: [
          { number: 1, cells: ["Date", "Site", null, "Gallons"] },
          { number: 3, cells: ["02/10/2025", "Richmond", null, "450"] },
        ] },
      ],
    };
    const onPickAmong = vi.fn();
    render(
      <DocumentContentView
        documentId="DOC"
        selectedId="gallons"
        onPickAmong={onPickAmong}
        marks={marks(["gallons", { kind: "cell", sheet: "2025 log", row: 3, column: 3 }, "450"])}
      />
    );
    const cell = await screen.findByRole("button", { name: "Select gallons" });
    expect(cell.textContent).toBe("450");
    expect(screen.getByRole("tab", { name: "2025 log" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["", "A", "B", "C", "D"]);
    expect(screen.getByRole("rowheader", { name: "3" })).toBeTruthy(); // the workbook's own row number
    fireEvent.click(cell);
    expect(onPickAmong).toHaveBeenCalledWith(["gallons"]);
  });

  it("finds a CSV value's cell in its row by the value's text", async () => {
    content.body = { kind: "sheets", truncated: false, sheets: [{ name: null, columns: 3, rows: [
      { number: 1, cells: ["Date", "Product", "Gallons"] },
      { number: 2, cells: ["02/10/2025", "Diesel", "450"] },
    ] }] };
    render(
      <DocumentContentView
        documentId="DOC"
        selectedId={null}
        marks={marks(["fuel", { kind: "row", row: 2 }, "Diesel"], ["site", { kind: "row", row: 2 }, "Richmond"])}
      />
    );
    expect((await screen.findByRole("button", { name: "Select fuel" })).textContent).toBe("Diesel");
    // Not in any single cell: the row number is the mark.
    expect(screen.getByRole("button", { name: "Select site" }).textContent).toBe("2");
  });

  it("says when the file cannot be shown", async () => {
    const { api } = await import("../../../lib/api");
    vi.mocked(api).mockRejectedValueOnce(new Error("415"));
    render(<DocumentContentView documentId="DOC" selectedId={null} marks={[]} />);
    expect(await screen.findByText(/cannot be shown here/)).toBeTruthy();
  });
});

describe("from the extraction to the review screen", () => {
  const evidence = [{ documentId: "DOC", filename: "bill.docx", format: "docx" }] as unknown as EvidenceItem[];
  const field = (name: string, value: string, block: string): ExtractedField => ({
    documentId: "DOC", canonicalTypeId: "CT-S2-ELEC", fieldKey: name, fieldLabel: name, value, unit: null,
    valueProperties: [], fieldState: "populated", snippet: null, snippetContext: null,
    location: { kind: "page", page: 1, region: null }, reviewStatus: "unreviewed", correctedValue: null,
    valueOrigin: "extracted",
    reviewToken: encodeReviewCandidateToken({
      document_id: "DOC", field_name: name, display_label: name, raw_value: value, normalized_value: value,
      unit: null, source_reference: { page_number: 1, parser_block_ids: [block] },
    }),
  });

  it("gives a Word value its line and text, and a click on the line selects its card", async () => {
    const values: ReviewValue[] = reviewValuesFromFields(
      [field("account_number", "KGE-7781-B", "docx_parser-p1-b1"), field("activity_quantity", "96,000", "docx_parser-p1-b2")],
      evidence
    );
    expect(values.map((v) => [v.anchor, v.rawText])).toEqual([
      [{ kind: "line", line: 1 }, "KGE-7781-B"],
      [{ kind: "line", line: 2 }, "96,000"],
    ]);
    content.body = { kind: "lines", truncated: false, lines: ["Account Number\tKGE-7781-B", "Total kWh Used\t96,000 kWh"] };
    render(
      <ExtractionReview
        engagement={engagementConfig}
        values={values}
        onValuesChange={() => {}}
        initialDocumentId="DOC"
        onSaveAsk={() => {}}
        onBack={() => {}}
        renderPage={(documentId, _span, _box, pageMarks, pick) => (
          <DocumentContentView documentId={documentId} marks={pageMarks ?? []} selectedId={pick?.selectedId ?? null}
            onPickAmong={pick?.onPickAmong} />
        )}
      />
    );
    const selected = () => document.querySelector(".s1-xr-card.is-sel")?.textContent ?? "";
    fireEvent.click(await screen.findByRole("button", { name: /^Select activity_quantity/ }));
    expect(selected()).toContain("96,000");
    fireEvent.click(screen.getByRole("button", { name: /^Select account_number/ }));
    expect(selected()).toContain("KGE-7781-B");
  });
});

describe("review findings: the right spot, every time", () => {
  beforeEach(() => {
    content.body = {};
  });

  it("finds numbers only as whole tokens", () => {
    expect(findTokens("Invoice 01/12/2025 at 10:12", "12")).toEqual([]);
    expect(findTokens("Account 112, total 1,200 and 12.5", "12")).toEqual([]);
    expect(findTokens("Usage 1,200 kWh", "1200")).toEqual([[6, 11]]);
    expect(findTokens("Usage 1,200 kWh", "200")).toEqual([]);
    expect(findTokens("Gallons 12", "12")).toEqual([[8, 10]]);
  });

  it("reads CSV cells and workbook cells from the reference, whatever the file is called", () => {
    expect(anchorOf("csv", { cell_or_range: "E2", parser_block_ids: ["csv_parser-r2-b2"] }))
      .toEqual({ kind: "row", row: 2, column: 4 });
    expect(anchorOf("other", { sheet_name: "Log", cell_or_range: "F2" }))
      .toEqual({ kind: "cell", sheet: "Log", row: 2, column: 5 }); // an .xlsm
    expect(anchorOf("docx", { cell_or_range: "part 2", parser_block_ids: ["docx_parser-p1-b5"] }))
      .toEqual({ kind: "line", line: 5, part: 2 });
  });

  it("never marks a CSV value inside the date: its own column, else the one cell equal to it", async () => {
    content.body = { kind: "sheets", truncated: false, sheets: [{ name: null, columns: 7, rows: [
      { number: 2, cells: ["01/22/2025", "Richmond", "Chiller", "R-134a", "45", "0", "650"] },
      { number: 3, cells: ["04/09/2025", "Richmond", "RTU-5", "R-410A", "0", "0", "16"] },
    ] }] };
    render(
      <DocumentContentView
        documentId="DOC"
        selectedId={null}
        marks={marks(
          ["recovered", { kind: "row", row: 2, column: 5 }, "0"],
          ["recovered-old", { kind: "row", row: 2 }, "0"], // no column recorded: the one cell that is "0"
          ["added-ambiguous", { kind: "row", row: 3 }, "0"] // two cells are "0": the row, not a guess
        )}
      />
    );
    expect((await screen.findByRole("button", { name: "Select recovered · recovered-old" })).textContent).toBe("0");
    expect(screen.getByRole("button", { name: "Select added-ambiguous" }).textContent).toBe("3"); // the row number
  });

  it("marks a unit after the label, and in the part of the line the extractor read", async () => {
    content.body = { kind: "lines", truncated: false, lines: [
      "Total kWh Used: 96,000 kWh",
      "Meter M-1\tTotal kWh Used\t96,000 kWh",
      "Account Number\tKGE-7781-B",
    ] };
    render(
      <DocumentContentView
        documentId="DOC"
        selectedId={null}
        marks={marks(
          ["unit-colon", { kind: "line", line: 1 }, "kWh"],
          ["unit-tabs", { kind: "line", line: 2 }, "kWh"],
          ["account", { kind: "line", line: 3, part: 2 }, "KGE-7781-B"]
        )}
      />
    );
    const colon = await screen.findByRole("button", { name: "Select unit-colon" });
    expect(colon.previousSibling?.textContent).toBe("Total kWh Used: 96,000 ");
    expect(screen.getByRole("button", { name: "Select unit-tabs" }).previousSibling?.textContent)
      .toBe("Meter M-1\tTotal kWh Used\t96,000 ");
    expect(screen.getByRole("button", { name: "Select account" }).textContent).toBe("KGE-7781-B");
  });

  it("keeps every other value on a line marked when one value's text is not on it", async () => {
    content.body = { kind: "lines", truncated: false, lines: ["07/03/2025  Card ****  Diesel  12.4 gal"] };
    const onPickAmong = vi.fn();
    render(
      <DocumentContentView
        documentId="DOC"
        selectedId="card"
        onPickAmong={onPickAmong}
        marks={marks(["card", { kind: "line", line: 1 }, "****1182"], ["qty", { kind: "line", line: 1, part: 4 }, "12.4"])}
      />
    );
    const card = await screen.findByRole("button", { name: "Select card" });
    expect(card.textContent).toBe("1"); // on the line number
    expect(card.className).toContain("s1-cv__mark--selected");
    fireEvent.click(screen.getByRole("button", { name: "Select qty" }));
    expect(onPickAmong).toHaveBeenCalledWith(["qty"]);
  });

  it("opens the selected value's own sheet again after another tab was looked at", async () => {
    content.body = { kind: "sheets", truncated: false, sheets: [
      { name: "Log", columns: 1, rows: [{ number: 1, cells: ["450"] }] },
      { name: "Notes", columns: 1, rows: [{ number: 1, cells: ["memo"] }] },
    ] };
    const valueMarks = marks(["x", { kind: "cell", sheet: "Log", row: 1, column: 0 }, "450"],
      ["y", { kind: "cell", sheet: "Notes", row: 1, column: 0 }, "memo"]);
    const view = render(<DocumentContentView documentId="DOC" selectedId="x" marks={valueMarks} />);
    await screen.findByRole("button", { name: "Select x" });
    fireEvent.click(screen.getByRole("tab", { name: "Notes" }));
    view.rerender(<DocumentContentView documentId="DOC" selectedId="y" marks={valueMarks} />);
    view.rerender(<DocumentContentView documentId="DOC" selectedId="x" marks={valueMarks} />);
    expect(screen.getByRole("tab", { name: "Log" }).getAttribute("aria-selected")).toBe("true");
  });
});

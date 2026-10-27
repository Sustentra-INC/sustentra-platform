/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { encodeReviewCandidateToken } from "../adapters/fieldAdapter";
import { reviewValuesFromFields } from "../adapters/reviewValueAdapter";
import { ExtractionReview } from "../components/ExtractionReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EvidenceItem, ExtractedField } from "../types";

/**
 * A backend value's scope chip says where it counts, as the demo's do: an electricity quantity
 * is one "Scope 2 · location- and market-based" chip (both bases are computed from it), a
 * fuel or refrigerant quantity is Scope 1, the fields that say whose, where and when are
 * General, and the rest are Not placed. Before, every field of an electricity bill (its account
 * number, its dates) read "Scope 2 · location-based", and market-based never showed.
 */
function field(canonicalTypeId: string | null, name: string, value: string): ExtractedField {
  return {
    documentId: "DOC-1",
    canonicalTypeId,
    fieldKey: `candidate:${name}`,
    reviewToken: encodeReviewCandidateToken({
      candidate_id: name, evidence_id: "EV-1", document_id: "DOC-1", field_name: name, display_label: name,
      normalized_value: value, unit: null,
    }),
    fieldLabel: name,
    value,
    unit: null,
    valueProperties: [],
    fieldState: "populated",
    snippet: null,
    snippetContext: null,
    location: null,
    reviewStatus: "unreviewed",
    correctedValue: null,
    valueOrigin: "extracted",
  };
}
const DOC = { documentId: "DOC-1", filename: "kent_electric_feb_2025.pdf", format: "pdf", uploadedAt: "2026-10-20T09:00:00Z",
  detectedType: "Electricity bill" } as unknown as EvidenceItem;

const scopes = (canonicalTypeId: string | null, names: string[]) =>
  Object.fromEntries(reviewValuesFromFields(names.map((n) => field(canonicalTypeId, n, "x")), [DOC]).map((v) => [v.whatItIs, v.scope]));

describe("where a backend value counts", () => {
  it("places an electricity or thermal quantity in both Scope 2 bases, and the bill's other fields by what they are", () => {
    for (const type of ["CT-S2-ELEC", "CT-S2-THERMAL"]) {
      expect(scopes(type, ["activity_quantity", "activity_unit", "energy_type", "account_number", "service_period_start", "facility_name", "service_address", "supplier_name", "meter_number"])).toEqual({
        activity_quantity: "scope2_both",
        activity_unit: "scope2_both",
        energy_type: "scope2_both",
        account_number: "general",
        service_period_start: "general",
        facility_name: "general",
        service_address: "general",
        supplier_name: "general",
        meter_number: "not_placed",
      });
    }
  });

  it("places fuel and refrigerant figures in Scope 1, and a quantity of an unknown type nowhere", () => {
    expect(scopes("CT-S1-MOBFUEL", ["activity_quantity", "fuel_type", "transaction_date", "vehicle_or_equipment_id", "biofuel_blend_pct"])).toEqual({
      activity_quantity: "scope1",
      fuel_type: "scope1",
      transaction_date: "general",
      vehicle_or_equipment_id: "general",
      biofuel_blend_pct: "not_placed",
    });
    expect(scopes("CT-S1-REFRSVC", ["refrigerant_added", "refrigerant_recovered", "equipment_capacity", "service_type", "refrigerant_type", "equipment_id", "service_date"])).toEqual({
      refrigerant_added: "scope1",
      refrigerant_recovered: "scope1",
      equipment_capacity: "scope1",
      service_type: "scope1",
      refrigerant_type: "scope1",
      equipment_id: "general",
      service_date: "general",
    });
    expect(scopes(null, ["activity_quantity"])).toEqual({ activity_quantity: "not_placed" });
  });
});

describe("a backend electricity card's chips", () => {
  it("shows one chip for both Scope 2 bases, and says so on the request", () => {
    const values = reviewValuesFromFields(
      [field("CT-S2-ELEC", "activity_quantity", "182.4"), field("CT-S2-ELEC", "account_number", "ACC-77")],
      [DOC]
    );
    const { container } = render(
      <ExtractionReview
        engagement={engagementConfig}
        values={values}
        onValuesChange={vi.fn()}
        initialDocumentId="DOC-1"
        initialValueId="candidate:activity_quantity"
        onSaveAsk={vi.fn()}
        onBack={vi.fn()}
      />
    );
    const chips = (card: Element) => Array.from(card.querySelectorAll(".s1-xr-scope")).map((c) => [c.textContent, c.className]);
    const [quantity, account] = Array.from(container.querySelectorAll(".s1-xr-card"));
    expect(chips(quantity)).toEqual([["Scope 2 · location- and market-based", "s1-xr-scope s1-xr-scope--scope2_location"]]);
    expect(chips(account)).toEqual([["General", "s1-xr-scope s1-xr-scope--general"]]);

    fireEvent.click(within(quantity as HTMLElement).getByRole("button", { name: "Request" }));
    const about = document.querySelector(".s1-atr__about")!;
    expect(about.getAttribute("title")).toContain(" · Scope 2 · location- and market-based · ");
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toContain("Scope 2 · location- and market-based");
  });
});

/* @vitest-environment jsdom */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const response = vi.hoisted(() => ({ body: {} as unknown }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn(() => Promise.resolve(response.body)),
}));

import { liveResultsFromRecalculation } from "../adapters/recalculationResultsAdapter";
import type { Recalculation } from "../api/recalculation";
import { BackendOutputScreen } from "../components/BackendOutputScreen";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EngagementConfig, EvidenceItem } from "../types";
import type { Finding } from "../types/verification";
import { liveStatementFigures } from "../utils/outputStatement";
import liveExample from "./fixtures/recalculationLive.json";
import workbookExample from "./fixtures/recalculationWorkbookExample.json";

const RESULT = workbookExample as unknown as Recalculation;
/** The backend's own response for a mid-review engagement (see liveResults.test.tsx). */
const LIVE = liveExample as unknown as Recalculation;
const pending = (document_id: string) => ({
  document_id, record: `${document_id}.pdf`, canonical_type_id: "CT-S2-ELEC", fields: ["activity_quantity"],
});

function renderOutput(result: Recalculation, extra: Partial<EngagementConfig> = {}, findings: Finding[] = []) {
  response.body = result;
  return render(
    <BackendOutputScreen
      engagement={{ ...engagementConfig, engagementId: result.engagement_id, ...extra }}
      evidence={Array.from({ length: 5 }, () => ({}) as EvidenceItem)}
      values={[]}
      asks={[]}
      findings={findings}
      onError={() => false}
    />
  );
}

async function basisLines(result: Recalculation): Promise<string[]> {
  renderOutput(result);
  const heading = await screen.findByRole("heading", { name: "Basis of evidence" });
  return within(heading.parentElement as HTMLElement).getAllByRole("listitem").map((li) => li.textContent ?? "");
}

describe("basis of evidence on Output", () => {
  it("counts fully reviewed documents, then the ones with values awaiting review", async () => {
    // 4 documents read: 1 fully reviewed; a partly reviewed CSV and two scans still have values awaiting review.
    const lines = await basisLines({
      ...RESULT,
      documents_considered: 4,
      documents_reviewed: 1,
      awaiting_review: [pending("SCAN-1"), pending("SCAN-2"), pending("DIESEL-CSV")],
    });
    expect(lines[0]).toBe("5 source documents");
    expect(lines).toContain("1 fully reviewed document (3 more with values awaiting review)");
  });

  it("keeps the old wording for results without documents_reviewed", async () => {
    expect(RESULT.documents_reviewed).toBeUndefined();
    expect(await basisLines(RESULT)).toContain("4 document(s) with reviewed values");
  });
});

describe("the live statement", () => {
  const live = liveResultsFromRecalculation(LIVE);
  const statement = liveStatementFigures(live.lines, live.boxTotals, live.inventory, LIVE.tolerance_pct);

  it("adds up Scope 1 and Scope 2 from the roll-up, against both reported scope totals", () => {
    expect(statement.location).toMatchObject({ reported: 2020, partial: true });
    expect(statement.location.recomputed).toBeCloseTo(1842.902, 3);
    expect(statement.market).toMatchObject({ reported: 1900, partial: true });
    expect(statement.misstatement).toBeCloseTo(1842.902 - 2020, 3);
    expect(statement.materialityTonnes).toBeCloseTo(101, 6);
    expect(statement.materialityBase).toBe("reported");
  });

  it("lists categories and scope totals with honest outcomes", () => {
    const row = Object.fromEntries(statement.rows.map((r) => [`${r.label}|${r.basis}`, r]));
    expect(row["Scope 1 · stationary combustion|Natural Gas"]).toMatchObject({ reported: 1250, outcome: null, state: { label: "Partial · 1 open" } });
    expect(row["Scope 1 · fugitive emissions|R-410A"]).toMatchObject({ reported: null, reportedNote: "Not entered", outcome: null });
    expect(row["Scope 1 total|"]).toMatchObject({ total: true, reported: 1600, state: { label: "Incomplete" } });
    expect(row["Scope 2 · electricity|Location-based"]).toMatchObject({ reported: 348.14, outcome: "agrees" });
    expect(row["Scope 2 location-based total|"]).toMatchObject({ reported: 420, outcome: "differs" });
    expect(row["Scope 2 · electricity|Market-based"]).toMatchObject({ reported: null, reportedNote: "Total only" });
    expect(row["Scope 2 market-based total|"]).toMatchObject({ reported: 300, outcome: "material" });
    // Not calculated, not in scope and no-evidence rows have nothing to state.
    expect(statement.rows.some((r) => r.label.includes("process") || r.label.includes("heating"))).toBe(false);
  });

  it("drafts the conclusion from what compares, and names what cannot be compared yet", () => {
    expect(statement.materialBoxes).toEqual([{ title: "Scope 2, market-based", pctMaterial: expect.closeTo(0.089, 3) }]);
    expect(statement.openBoxes).toEqual([{ title: "Scope 1", state: expect.objectContaining({ label: "Incomplete" }) }]);
    expect(statement.differences.map((d) => d.label)).toEqual([
      "Scope 1 total",
      "Scope 2 market-based total",
      "Scope 1 · stationary combustion",
      "Scope 2 location-based total",
    ]);
  });

  it("renders as the demo's document: draft band, real Excel download, recalculated figures, honest sign-off", async () => {
    const finding: Finding = {
      id: "F-1", dataPointId: "vr:s1-stationary:natural-gas", dataPointLabel: "Natural gas", sentence: "April bill missing.",
      cause: "Completeness", magnitude: "n/a", status: "Open", withClientSince: null, registeredBy: "Dana",
    };
    renderOutput(
      LIVE,
      {
        clientName: "Acme Foods",
        signedInName: "Dana",
        boundaryApproach: "Operational control",
        engagementTeam: [{ name: "Dana Reyes", login: "dana@verifier.test" }],
      },
      [finding]
    );
    await screen.findByText("Draft working paper · not an assurance opinion");
    const download = screen.getByRole("link", { name: /Download workpaper \(Excel\)/ });
    expect(download.getAttribute("href")).toBe("/api/v1/engagements/ENG-1/export");
    // The demo's toast-only exports are not offered here.
    expect(screen.queryByRole("button", { name: /Corrections register|Evidence index|Download statement/ })).toBeNull();
    expect(screen.getByText("Operational control")).toBeTruthy();
    expect(screen.getByText(/differs from the evidence by \+8\.9% of its reported total/)).toBeTruthy();
    expect(screen.getByText(/Not compared yet: Scope 1 \(incomplete\)/)).toBeTruthy();
    expect(screen.getByText(/The verifier writes the conclusion when the report is issued/)).toBeTruthy();
    expect(screen.queryByText(/nothing has come to our attention/)).toBeNull();
    expect(screen.getAllByText("1,843")).toHaveLength(2); // the accent tile and the table's footer, whole tonnes
    expect(screen.getByText("Reported 2,020 · partial: at least this")).toBeTruthy();
    expect(screen.getByText("Checked by system")).toBeTruthy();
    expect(screen.getByText(/April bill missing\./)).toBeTruthy();
    expect(screen.getByText("Prepared by Dana")).toBeTruthy();
    expect(screen.getByText("Not issued")).toBeTruthy();
    // None of the demo's hard-coded identity.
    expect(screen.getByRole("heading", { name: "Acme Foods" })).toBeTruthy();
    expect(screen.getByText("Dana Reyes")).toBeTruthy(); // the engagement team, in place of the demo's verifier firm
    expect(screen.queryByText(/Meridian|M\. Osei|Cascade Provisions/)).toBeNull();
  });
});

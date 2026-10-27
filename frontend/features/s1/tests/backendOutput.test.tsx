/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const response = vi.hoisted(() => ({ body: {} as unknown }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn(() => Promise.resolve(response.body)),
}));

import type { Recalculation } from "../api/recalculation";
import { BackendOutputScreen } from "../components/BackendOutputScreen";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EvidenceItem } from "../types";
import workbookExample from "./fixtures/recalculationWorkbookExample.json";

const RESULT = workbookExample as unknown as Recalculation;
const pending = (document_id: string) => ({
  document_id, record: `${document_id}.pdf`, canonical_type_id: "CT-S2-ELEC", fields: ["activity_quantity"],
});

async function basisLine(result: Recalculation): Promise<string | null> {
  response.body = result;
  render(
    <BackendOutputScreen
      engagement={{ ...engagementConfig, engagementId: result.engagement_id }}
      evidence={Array.from({ length: 5 }, () => ({}) as EvidenceItem)}
      values={[]}
      asks={[]}
      findings={[]}
      onError={() => false}
    />
  );
  return (await screen.findByText(/documents uploaded/)).textContent;
}

describe("basis of evidence on Output", () => {
  it("counts fully reviewed documents, then the ones with values awaiting review", async () => {
    // 4 documents read: 1 fully reviewed; a partly reviewed CSV and two scans still have values awaiting review.
    const line = await basisLine({
      ...RESULT,
      documents_considered: 4,
      documents_reviewed: 1,
      awaiting_review: [pending("SCAN-1"), pending("SCAN-2"), pending("DIESEL-CSV")],
    });
    expect(line).toBe("5 documents uploaded, 1 fully reviewed (3 more with values awaiting review)");
  });

  it("keeps the old wording for results without documents_reviewed", async () => {
    expect(RESULT.documents_reviewed).toBeUndefined();
    expect(await basisLine(RESULT)).toBe("5 documents uploaded, 4 with reviewed values");
  });
});

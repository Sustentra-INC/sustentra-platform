import { describe, expect, it } from "vitest";
import { newLineProblem, stampDemoLines } from "../demo-backend/linesModel";
import { addedByText } from "../utils/formatPeriod";
import type { EngagementConfig } from "../types/engagement";

const engagement = {
  facilities: [{ facilityId: "fac-kc01", name: "Kansas City Plant" }, { facilityId: "", name: "Müller Käserei – Zürich" }],
  evidenceLines: [],
} as unknown as EngagementConfig;

const line = (over: Record<string, unknown> = {}) => ({
  category: "stationary", level2_label: "Propane", anchor_kind: "facility" as const, anchor_id: "fac-kc01", label: "Propane", ...over,
});

describe("the demo checks new line anchors like the server", () => {
  it("accepts a Setup facility, including one with no id", () => {
    expect(newLineProblem(engagement, [line()])).toBeNull();
    expect(newLineProblem(engagement, [line({ anchor_id: "name-m-ller-k-serei-z-rich" })])).toBeNull();
  });
  it("refuses an unknown facility, a name with no letters, and an engagement with no facilities", () => {
    expect(newLineProblem(engagement, [line({ anchor_id: "fac-gone" })])).toMatch(/isn't in Setup/);
    expect(newLineProblem(engagement, [line({ level2_label: "燃料" })])).toMatch(/letters or numbers/);
    expect(newLineProblem({ ...engagement, facilities: [] }, [line()])).toMatch(/Add a facility in Setup first/);
  });
  it("allows a company-wide contractual line and a contractual line on a facility, and refuses company for others", () => {
    const none = { ...engagement, facilities: [] } as unknown as EngagementConfig;
    const ppa = { category: "contractual", level2_label: "PPAs", label: "PPAs" };
    expect(newLineProblem(none, [{ ...ppa, anchor_kind: "company" as const, anchor_id: "company" }])).toBeNull();
    expect(newLineProblem(engagement, [{ ...ppa, anchor_kind: "facility" as const, anchor_id: "fac-kc01" }])).toBeNull();
    expect(newLineProblem(engagement, [line({ anchor_kind: "company", anchor_id: "company" })])).toMatch(/Only contractual/);
  });
  it("leaves a line that is already saved alone", () => {
    const saved = { ...engagement, facilities: [], evidenceLines: [line()] } as unknown as EngagementConfig;
    expect(newLineProblem(saved, [line()])).toBeNull();
  });
});

describe("who added a line, and when", () => {
  const NOW = "2025-11-04T12:00:00.000Z";
  it("stamps a new line once and keeps the stamp through a rename, ignoring what the caller sent", () => {
    const first = stampDemoLines(engagement, [line({ created_by: "forged", created_at: "2001-01-01T00:00:00Z" })], "j.park@acme.test", NOW);
    expect(first[0]).toMatchObject({ created_by: "j.park@acme.test", created_at: NOW });
    const saved = { ...engagement, evidenceLines: first } as unknown as EngagementConfig;
    const renamed = stampDemoLines(saved, [{ ...first[0], label: "Propane, Kent", created_by: "someone-else" }], "k.lee@acme.test", "2025-12-01T12:00:00.000Z");
    expect(renamed[0]).toMatchObject({ label: "Propane, Kent", created_by: "j.park@acme.test", created_at: NOW });
  });
  it("reads as 'Added by J. Park \u00b7 Nov 4' and copes with missing or unusual names", () => {
    expect(addedByText("Jane Park", NOW)).toBe("Added by J. Park \u00b7 Nov 4");
    expect(addedByText("M\u00fcller K\u00e4serei \u2013 Z\u00fcrich", NOW)).toBe("Added by M\u00fcller K\u00e4serei \u2013 Z\u00fcrich \u00b7 Nov 4");
    expect(addedByText("\u738b\u82b3 \u674e", NOW)).toBe("Added by \u738b. \u674e \u00b7 Nov 4");
    expect(addedByText("j.park@acme.test", NOW)).toBe("Added by j.park@acme.test \u00b7 Nov 4");
    expect(addedByText(null, null)).toBe("Added by a reviewer");
    expect(addedByText("Jane Park", "not a date")).toBe("Added by J. Park");
  });
});

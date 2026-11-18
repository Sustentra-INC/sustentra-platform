import { describe, expect, it } from "vitest";
import { newLineProblem } from "../demo-backend/linesModel";
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

import { describe, expect, it } from "vitest";

import { resultsViewForLine, scheduleViewForLine } from "../pages/lineLinks";

describe("links between a line's schedule and its calculation panel", () => {
  const key = "s1:stationary:natural-gas:fac-kc01";

  it("opens Verification results focused on the line the schedule names", () => {
    expect(resultsViewForLine(key)).toEqual({ name: "results", lineKey: key });
  });

  it("opens the line's supporting schedule from its calculation panel", () => {
    expect(scheduleViewForLine(key)).toEqual({ name: "schedule", lineKey: key });
  });
});

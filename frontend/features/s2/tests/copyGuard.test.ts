import { describe, expect, it } from "vitest";

import { findBannedRenderedCopy } from "../utils/copyGuard";

describe("S2 rendered-copy guard", () => {
  it("detects banned words in rendered UI copy", () => {
    expect(findBannedRenderedCopy("all clear")).toContain("all clear");
  });

  it("allows adapter/backend terminology to be tested before it is rendered", () => {
    const backendStatus = "passed";
    const renderedCopy = "can evaluate";

    expect(backendStatus).toBe("passed");
    expect(findBannedRenderedCopy(renderedCopy)).toEqual([]);
  });
});


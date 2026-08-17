import { describe, expect, it } from "vitest";

import { getInventory, type S2FixtureMode } from "../fixtures/getInventory";

describe("S2 fixture contract", () => {
  it("makes every planned fixture mode reachable", () => {
    const modes: S2FixtureMode[] = [
      "meridian",
      "meridian-empty",
      "meridian-none-examined",
      "meridian-filtered-empty",
      "meridian-loading",
      "meridian-error",
      "meridian-degraded",
      "meridian-blocked",
      "meridian-complete",
    ];

    for (const mode of modes) {
      expect(getInventory(mode).mode).toBe(mode);
    }
  });

  it("uses the supplied Meridian fixture as source of truth", () => {
    const fixture = getInventory("meridian");

    expect(fixture.lines).toHaveLength(8);
    expect(fixture.findings).toHaveLength(8);
    expect(fixture.requests).toHaveLength(3);
    expect(fixture.documents).toHaveLength(8);
  });
});


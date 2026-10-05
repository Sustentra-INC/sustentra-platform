import { describe, expect, it } from "vitest";

import { nextKeyboardIndex } from "../utils/keyboardNavigation";

describe("keyboard navigation", () => {
  it("moves down without passing the final row", () => {
    expect(nextKeyboardIndex(0, 3, "down")).toBe(1);
    expect(nextKeyboardIndex(2, 3, "down")).toBe(2);
  });

  it("moves up without passing the first row", () => {
    expect(nextKeyboardIndex(2, 3, "up")).toBe(1);
    expect(nextKeyboardIndex(0, 3, "up")).toBe(0);
  });

  it("returns -1 when there are no rows", () => {
    expect(nextKeyboardIndex(0, 0, "down")).toBe(-1);
  });
});

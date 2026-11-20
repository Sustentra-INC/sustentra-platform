/* @vitest-environment jsdom */
import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useOpenEngagement } from "../utils/useOpenEngagement";

describe("an answer that arrives after the user switched engagement", () => {
  it("is for the open engagement only, even though the check was made before the switch", async () => {
    const { result, rerender } = renderHook(({ id }) => useOpenEngagement(id), { initialProps: { id: "ENG-A" } });
    const stillOpen = result.current;
    expect(stillOpen("ENG-A")).toBe(true);

    // A request for A starts; the user switches to B; the answer lands.
    const answer = new Promise<string>((resolve) => setTimeout(() => resolve("A's lines"), 0));
    rerender({ id: "ENG-B" });
    const landed = await answer;
    expect(landed).toBe("A's lines");
    expect(stillOpen("ENG-A")).toBe(false); // dropped: it is not written into B
    expect(stillOpen("ENG-B")).toBe(true);
    expect(result.current).toBe(stillOpen); // one stable function, so a request keeps asking the same thing
  });

  it("follows the user back to the first engagement", () => {
    const { result, rerender } = renderHook(({ id }) => useOpenEngagement(id), { initialProps: { id: "ENG-A" } });
    rerender({ id: "ENG-B" });
    rerender({ id: "ENG-A" });
    expect(result.current("ENG-A")).toBe(true);
  });
});

import { describe, expect, it } from "vitest";
import { suggestedBy } from "../components/BackendMethodologyReview";

describe("suggestedBy", () => {
  it("names the rules for a value Sustentra's rules read, and the AI otherwise", () => {
    expect(suggestedBy("rules")).toBe("Sustentra's rules");
    expect(suggestedBy("ai")).toBe("Sustentra's AI");
    expect(suggestedBy(undefined)).toBe("Sustentra's AI");
  });
});

import { describe, expect, it } from "vitest";

import { parseViewFromSearch } from "../../s1/utils/viewHistory";
import { dataPointLineLink, documentLink, engagementLink, methodologyRowLink } from "../taskLinks";

const asSearch = (link: string) => link.slice(1); // "/?a=b" -> "?a=b"

describe("task links", () => {
  it("are in-app paths that the workpaper opens", () => {
    for (const link of [
      documentLink("D1", "E1"),
      dataPointLineLink("s1:stationary:natural-gas:fac-1", "E1"),
      methodologyRowLink("consolidation_approach", "E1"),
      engagementLink("E1"),
    ]) {
      expect(link.startsWith("/?")).toBe(true);
      expect(link.startsWith("//")).toBe(false);
      expect(parseViewFromSearch(asSearch(link))).not.toBeNull();
    }
  });

  it("name the document, line, methodology screen and engagement", () => {
    expect(parseViewFromSearch(asSearch(documentLink("D 1", "E1")))).toMatchObject({ name: "extraction", documentId: "D 1" });
    expect(parseViewFromSearch(asSearch(dataPointLineLink("s1:a:b:c", "E1")))).toEqual({ name: "schedule", lineKey: "s1:a:b:c" });
    expect(parseViewFromSearch(asSearch(methodologyRowLink("gwp", "E1")))).toEqual({ name: "methodology" });
    expect(methodologyRowLink("gwp", "E1")).toContain("row=gwp");
    expect(documentLink("D1", "E1")).toContain("e=E1");
    expect(parseViewFromSearch(asSearch(engagementLink("E1")))).toEqual({ name: "dashboard" });
  });

  it("keep unusual characters safe in the query string", () => {
    const link = documentLink("a&b=c d", "E/1");
    expect(link).not.toContain(" ");
    expect(new URLSearchParams(link.slice(2)).get("doc")).toBe("a&b=c d");
  });
});

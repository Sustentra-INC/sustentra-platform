import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { StateIndicator } from "../components/StateIndicator";

describe("StateIndicator", () => {
  it("renders a visible unmapped marker for unknown dimension/value pairs", () => {
    const html = renderToStaticMarkup(
      <StateIndicator dimension="processing" value="unknown" label="Unknown" />
    );

    expect(html).toContain("unmapped: Unknown");
    expect(html).toContain("s1-state--unmapped");
  });
});

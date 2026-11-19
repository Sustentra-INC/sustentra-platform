/* @vitest-environment jsdom */
import { describe, expect, it } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";

import { EstimatedReadNote } from "../components/AiValueNote";

describe("the estimated read note on a value's card", () => {
  it("says 'Estimated read' when the bill says the reading was estimated", () => {
    render(<EstimatedReadNote value={{ estimatedRead: true }} />);
    expect(screen.getByTestId("estimated-read-note")).toHaveTextContent("Estimated read");
  });

  it("says nothing for a value read from the meter", () => {
    const { container } = render(<EstimatedReadNote value={{}} />);
    expect(container).toBeEmptyDOMElement();
  });
});

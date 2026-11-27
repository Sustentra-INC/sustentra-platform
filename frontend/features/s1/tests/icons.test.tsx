// @vitest-environment jsdom
/**
 * Smoke tests for the two-tone icon set (MVP-263).
 *
 * Each icon must:
 *   1. Render without throwing.
 *   2. Produce a <svg> with viewBox="0 0 24 24".
 *   3. Be aria-hidden when no aria-label is provided.
 *   4. Expose an aria-label when one is passed.
 *   5. Accept a custom size.
 */
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import * as Icons from "../components/icons";

const ALL_ICONS = Object.entries(Icons).filter(
  ([key, val]) => key.startsWith("Icon") && typeof val === "function",
) as [string, Icons.IconProps extends never ? never : React.ComponentType<Icons.IconProps>][];

describe("icon set smoke tests", () => {
  it("exports at least 40 icons", () => {
    expect(ALL_ICONS.length).toBeGreaterThanOrEqual(40);
  });

  it.each(ALL_ICONS)("%s renders without throwing", (_name, Icon) => {
    expect(() => render(<Icon />)).not.toThrow();
  });

  it.each(ALL_ICONS)("%s has viewBox='0 0 24 24'", (_name, Icon) => {
    const { container } = render(<Icon />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg!.getAttribute("viewBox")).toBe("0 0 24 24");
  });

  it.each(ALL_ICONS)("%s is aria-hidden by default", (_name, Icon) => {
    const { container } = render(<Icon />);
    const svg = container.querySelector("svg");
    expect(svg!.getAttribute("aria-hidden")).toBe("true");
  });

  it.each(ALL_ICONS)("%s uses aria-label when provided", (_name, Icon) => {
    const { container } = render(<Icon aria-label="test label" />);
    const svg = container.querySelector("svg");
    expect(svg!.getAttribute("aria-label")).toBe("test label");
    expect(svg!.getAttribute("aria-hidden")).toBeNull();
  });

  it.each(ALL_ICONS)("%s accepts a custom size", (_name, Icon) => {
    const { container } = render(<Icon size={32} />);
    const svg = container.querySelector("svg");
    expect(svg!.getAttribute("width")).toBe("32");
    expect(svg!.getAttribute("height")).toBe("32");
  });
});

describe("icon aliases", () => {
  it("IconDocument is the same component as IconEvidence", () => {
    expect(Icons.IconDocument).toBe(Icons.IconEvidence);
  });
});

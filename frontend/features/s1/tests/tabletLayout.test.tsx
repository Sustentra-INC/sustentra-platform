/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { S1Chrome } from "../components/S1Chrome";
import { engagementConfig } from "../fixtures/engagementConfig";

/** A screen of `width` px: only the media queries that width satisfies match. */
function screenOf(width: number) {
  window.matchMedia = ((query: string) => {
    const min = /min-width:\s*([\d.]+)rem/.exec(query);
    const max = /max-width:\s*([\d.]+)rem/.exec(query);
    const ok = (!min || width >= Number(min[1]) * 16) && (!max || width <= Number(max[1]) * 16);
    return { matches: ok, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} };
  }) as unknown as typeof window.matchMedia;
}

const sidebar = () => document.querySelector(".s1-side") as HTMLElement;
const css = readFileSync(join(process.cwd(), "features", "s1", "styles", "s1-workpaper.css"), "utf8");
const rule = (selector: string) => new RegExp(`${selector.replace(/[.[\]]/g, "\\$&")}\\s*\\{[^}]*\\}`, "g");

afterEach(cleanup);

describe("a tablet (768 to 1024 px)", () => {
  it.each([768, 834, 1024])("starts with the icon rail at %i px, and the toggle opens the full sidebar", (width) => {
    screenOf(width);
    render(<S1Chrome engagement={engagementConfig}><p>content</p></S1Chrome>);
    expect(sidebar()).toHaveClass("s1-side--min");
    fireEvent.click(screen.getByRole("button", { name: /sidebar/i }));
    expect(sidebar()).not.toHaveClass("s1-side--min");
  });

  it.each([1025, 1440])("keeps the full sidebar at %i px", (width) => {
    screenOf(width);
    render(<S1Chrome engagement={engagementConfig}><p>content</p></S1Chrome>);
    expect(sidebar()).not.toHaveClass("s1-side--min");
  });

  it("keeps the full sidebar (the phone's top bar takes over by CSS) under 768 px", () => {
    screenOf(600);
    render(<S1Chrome engagement={engagementConfig}><p>content</p></S1Chrome>);
    expect(sidebar()).not.toHaveClass("s1-side--min");
  });
});

describe("the stylesheet's tablet rules", () => {
  it("turns the sidebar into a top bar only under 768 px, so a 768 px tablet keeps its sidebar", () => {
    expect(css).toMatch(/@media \(max-width: 47\.99rem\) \{\s*\.s1-shell \{ flex-direction: column; \}/);
    expect(css).toMatch(/@media \(max-width: 47\.99rem\) \{\s*\.s1-side, \.s1-side--min \{ width: 100%; \}/);
    expect(css).not.toMatch(/@media \(max-width: 48rem\) \{\s*\.s1-shell \{ flex-direction: column; \}/);
  });

  it("sizes the Output document with its padding inside its width", () => {
    expect(rule(".s1-out-doc").exec(css)?.[0]).toContain("box-sizing: border-box");
  });

  it("lets a request's state and buttons wrap in a narrow column", () => {
    expect(css).toMatch(/\.s1-req-state__row \{[^}]*flex-wrap: wrap/);
  });

  it("keeps an Evidence row's title, percent and actions on one row", () => {
    expect(css).toMatch(/\.s1-et-head \{ grid-template-columns: 1fr auto auto; \}/);
  });
});

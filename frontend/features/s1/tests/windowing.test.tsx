/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useWindowedRows } from "../hooks/useWindowedRows";
import type { Part } from "../utils/windowing";
import { offsetsOf, partsFor, sliceFor, WINDOW_THRESHOLD } from "../utils/windowing";

describe("windowing arithmetic", () => {
  const offsets = offsetsOf(500, () => undefined, 40); // 500 rows of 40 px

  it("draws the rows near the band and an empty spacer for the rest", () => {
    const slice = sliceFor(offsets, 4000, 4800, 400);
    expect(slice.start).toBe(90); // (4000 - 400) / 40
    expect(slice.end).toBe(130); // (4800 + 400) / 40
    const parts = partsFor(offsets, slice);
    const heights = parts.map((p) => (p.type === "spacer" ? p.height : 40));
    expect(parts[0]).toEqual({ type: "spacer", height: 90 * 40, key: "a" });
    expect(parts[parts.length - 1]).toEqual({ type: "spacer", height: (500 - 130) * 40, key: "c" });
    expect(heights.reduce((a, b) => a + b, 0)).toBe(500 * 40);
  });

  it("clamps at both ends and always draws a row", () => {
    expect(sliceFor(offsets, -5000, -4000, 100)).toEqual({ start: 0, end: 1 });
    expect(sliceFor(offsets, 99999, 100500, 100)).toEqual({ start: 499, end: 500 });
    expect(sliceFor(offsetsOf(0, () => undefined, 40), 0, 800, 100)).toEqual({ start: 0, end: 0 });
  });

  it("draws the focused row on its own, with a spacer to the window, rather than stretching the window", () => {
    const slice = sliceFor(offsets, 4000, 4800, 400);
    const parts = partsFor(offsets, slice, 3);
    const rows = parts.filter((p) => p.type === "row").map((p) => (p.type === "row" ? p.index : -1));
    expect(rows).toHaveLength(slice.end - slice.start + 1);
    expect(rows[0]).toBe(3);
    expect(rows.slice(1)[0]).toBe(slice.start);
    expect(parts[2]).toEqual({ type: "spacer", height: (slice.start - 4) * 40, key: "b" });
    expect(parts.map((p) => (p.type === "spacer" ? p.height : 40)).reduce((a, b) => a + b, 0)).toBe(500 * 40);
    const below = partsFor(offsets, slice, 400).filter((p) => p.type === "row");
    expect(below[below.length - 1]).toEqual({ type: "row", index: 400 });
    expect(partsFor(offsets, slice, 100)).toEqual(partsFor(offsets, slice)); // inside the window: nothing special
  });

  it("uses a row's measured height over the estimate", () => {
    const tall = offsetsOf(3, (i) => (i === 1 ? 200 : undefined), 40);
    expect(tall).toEqual([0, 40, 240, 280]);
  });
});

const ROW = 40;
let scrollY = 0;

function List({ count }: { count: number }) {
  const { host, onKeyDown, rowProps, enabled, parts } = useWindowedRows(count);
  const all: Part[] = enabled ? parts : Array.from({ length: count }, (_, index) => ({ type: "row" as const, index }));
  return (
    <div ref={host as (el: HTMLDivElement | null) => void} onKeyDown={onKeyDown} data-testid="list">
      {all.map((p) =>
        p.type === "spacer" ? (
          <div key={p.key} data-testid={p.key === "a" ? "before" : "after"} data-spacer={p.key} style={{ height: p.height }} />
        ) : (
          <div key={p.index} data-testid="row" {...rowProps(p.index)}>
            <button type="button">Open row {p.index}</button>
          </div>
        ),
      )}
    </div>
  );
}

const drawn = () => screen.getAllByTestId("row").map((r) => Number(r.textContent?.replace("Open row ", "")));

beforeEach(() => {
  scrollY = 0;
  Object.defineProperty(window, "innerHeight", { value: 800, configurable: true });
  // No layout in jsdom: the list starts at the top of the page (moving with the scroll), every row is 40 px.
  Element.prototype.getBoundingClientRect = function (this: Element) {
    const row = this.hasAttribute("data-win-index");
    const top = this.getAttribute("data-testid") === "list" ? -scrollY : 0;
    return { top, bottom: top + (row ? ROW : 0), height: row ? ROW : 0, left: 0, right: 0, width: 0, x: 0, y: top, toJSON: () => ({}) } as DOMRect;
  };
});
afterEach(cleanup);

describe("a long list draws a window", () => {
  it("draws everything at or under 100 rows", () => {
    render(<List count={WINDOW_THRESHOLD} />);
    expect(drawn()).toHaveLength(WINDOW_THRESHOLD);
    expect(screen.queryByTestId("before")).toBeNull();
    expect(screen.queryByTestId("after")).toBeNull();
  });

  it("draws far fewer rows than there are, with the rest as spacers, and the right rows after a scroll", async () => {
    render(<List count={500} />);
    await waitFor(() => expect(screen.getAllByTestId("row").length).toBeLessThan(60));
    expect(drawn()[0]).toBe(0);
    expect(screen.getByTestId("after")).toBeInTheDocument();
    scrollY = 6000; // row 150 is at the top of the screen
    act(() => {
      fireEvent.scroll(window);
    });
    await waitFor(() => expect(drawn()).toContain(150));
    const now = drawn();
    expect(now.length).toBeLessThan(60);
    expect(now).not.toContain(0);
    expect(now[0]).toBeLessThanOrEqual(150 - 10); // overscan above
    expect(now[now.length - 1]).toBeGreaterThanOrEqual(150 + 20); // the screen and overscan below
    // the spacers still add up to the whole list
    const before = Number(screen.getByTestId("before").style.height.replace("px", ""));
    const after = Number(screen.getByTestId("after").style.height.replace("px", ""));
    expect(before + now.length * ROW + after).toBeCloseTo(500 * ROW, -1);
  });

  it("Tab at the last drawn row draws the next rows and moves into the next one", async () => {
    render(<List count={500} />);
    await waitFor(() => expect(screen.getAllByTestId("row").length).toBeLessThan(60));
    const last = drawn()[drawn().length - 1];
    const button = screen.getByRole("button", { name: `Open row ${last}` });
    button.focus();
    fireEvent.keyDown(button, { key: "Tab" });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: `Open row ${last + 1}` })));
  });

  it("a row with the keyboard focus stays drawn when the list scrolls away", async () => {
    render(<List count={500} />);
    await waitFor(() => expect(screen.getAllByTestId("row").length).toBeLessThan(60));
    screen.getByRole("button", { name: "Open row 2" }).focus();
    scrollY = 12000;
    act(() => {
      fireEvent.scroll(window);
    });
    await waitFor(() => expect(drawn()).toContain(300));
    expect(drawn()).toContain(2);
  });
});

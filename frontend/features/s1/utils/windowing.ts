/**
 * Windowing for the Evidence page's long lists (MVP-160): a group of more than WINDOW_THRESHOLD rows draws only
 * the rows near the screen, with an empty spacer standing in for the rest, so 500 documents cost about as many
 * DOM nodes as 100. Pure arithmetic: the hook that reads the DOM is `useWindowedRows`.
 *
 * Rows are not all the same height (a facility note or a narrow screen wraps), so each row that has been drawn
 * is measured and keeps its measured height; a row not yet drawn counts as the average of the measured ones.
 */

/** A group with more rows than this draws a window of them. */
export const WINDOW_THRESHOLD = 100;
/** What a row not yet measured is assumed to measure, before any row has been. */
export const ESTIMATED_ROW_PX = 48;
/** How far beyond the screen rows are drawn, so a scroll or a find does not meet an empty spacer. */
export const OVERSCAN_PX = 600;
/** How many more rows a Tab at the edge of the window draws. */
export const TAB_STEP_ROWS = 20;

export interface WindowSlice {
  /** First row drawn. */
  start: number;
  /** One past the last row drawn. */
  end: number;
}

/** What to draw, top to bottom: a row, or an empty spacer of a height standing in for rows not drawn. */
export type Part = { type: "row"; index: number } | { type: "spacer"; height: number; key: string };

/** The top edge of every row, and the total height last: `count + 1` numbers. */
export function offsetsOf(count: number, heightOf: (index: number) => number | undefined, estimate: number): number[] {
  const offsets = new Array<number>(count + 1);
  offsets[0] = 0;
  for (let i = 0; i < count; i++) offsets[i + 1] = offsets[i] + (heightOf(i) ?? estimate);
  return offsets;
}

/**
 * The rows to draw for the visible band `[visibleTop, visibleBottom]` (px from the top of the list; either may
 * be outside the list), with `overscan` px more on each side. Always at least one row when there are any. (The
 * row with the keyboard focus is drawn on its own, wherever it is: see `partsFor`.)
 */
export function sliceFor(offsets: number[], visibleTop: number, visibleBottom: number, overscan: number): WindowSlice {
  const count = offsets.length - 1;
  if (count <= 0) return { start: 0, end: 0 };
  const top = visibleTop - overscan;
  const bottom = visibleBottom + overscan;
  // the first row whose bottom edge is below `top`
  let lo = 0;
  let hi = count - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (offsets[mid + 1] > top) hi = mid;
    else lo = mid + 1;
  }
  const start = lo;
  // the first row whose top edge is at or below `bottom`
  let a = start + 1;
  let b = count;
  while (a < b) {
    const mid = (a + b) >> 1;
    if (offsets[mid] >= bottom) b = mid;
    else a = mid + 1;
  }
  return { start, end: Math.min(Math.max(a, start + 1), count) };
}

/**
 * The window's rows with the spacers round them. ``pinned``: a row that must stay drawn (it has the keyboard
 * focus, or a Tab is moving into it); when it is outside the window it is drawn on its own, with a spacer for
 * the rows between it and the window, rather than the window stretching to reach it.
 */
export function partsFor(offsets: number[], slice: WindowSlice, pinned?: number): Part[] {
  const count = offsets.length - 1;
  if (count <= 0) return [];
  const end = Math.min(slice.end, count);
  const parts: Part[] = [];
  const space = (key: string, from: number, to: number) => {
    if (to > from && offsets[to] - offsets[from] > 0) parts.push({ type: "spacer", height: offsets[to] - offsets[from], key });
  };
  const rows = (from: number, to: number) => {
    for (let i = from; i < to; i++) parts.push({ type: "row", index: i });
  };
  const outside = pinned !== undefined && pinned >= 0 && pinned < count && (pinned < slice.start || pinned >= end);
  if (outside && pinned !== undefined && pinned < slice.start) {
    space("a", 0, pinned);
    rows(pinned, pinned + 1);
    space("b", pinned + 1, slice.start);
    rows(slice.start, end);
    space("c", end, count);
  } else if (outside && pinned !== undefined) {
    space("a", 0, slice.start);
    rows(slice.start, end);
    space("b", end, pinned);
    rows(pinned, pinned + 1);
    space("c", pinned + 1, count);
  } else {
    space("a", 0, slice.start);
    rows(slice.start, end);
    space("c", end, count);
  }
  return parts;
}

/** Whether two drawings are the same (so nothing needs to be drawn again). */
export function sameParts(a: Part[], b: Part[]): boolean {
  return (
    a.length === b.length &&
    a.every((p, i) => {
      const q = b[i];
      if (p.type === "row") return q.type === "row" && p.index === q.index;
      return q.type === "spacer" && p.key === q.key && Math.abs(p.height - q.height) < 1;
    })
  );
}

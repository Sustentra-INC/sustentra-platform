"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { flushSync } from "react-dom";

import {
  ESTIMATED_ROW_PX,
  OVERSCAN_PX,
  TAB_STEP_ROWS,
  WINDOW_THRESHOLD,
  offsetsOf,
  partsFor,
  sameParts,
  sliceFor,
  type Part,
  type WindowSlice,
} from "../utils/windowing";

interface Shown extends WindowSlice {
  /** What is drawn: the window's rows, a pinned row outside it, and the spacers between. */
  parts: Part[];
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** The nearest ancestor that scrolls the page's content, or null when the page itself scrolls. */
function scrollParent(el: HTMLElement | null): HTMLElement | null {
  for (let node = el?.parentElement ?? null; node; node = node.parentElement) {
    const overflow = getComputedStyle(node).overflowY;
    if ((overflow === "auto" || overflow === "scroll" || overflow === "overlay") && node.scrollHeight > node.clientHeight) return node;
  }
  return null;
}

const firstRows = (count: number): Shown => {
  const end = Math.min(count, 40);
  return { start: 0, end, parts: Array.from({ length: end }, (_, index) => ({ type: "row" as const, index })) };
};

/**
 * Draws only the rows of a long list that are near the screen (see `utils/windowing.ts`).
 *
 * Put `host` on the element that holds the rows (its top is where row 0 starts), draw `parts` in order (a row by
 * index, or an empty spacer of a height), and spread `rowProps(i)` on every drawn row. At or under `threshold`
 * rows everything is drawn and nothing here does anything, so a short list is exactly what it was.
 *
 * Kept working: the page's own find only meets drawn rows (the rows near the screen); Tab at the edge of the
 * window draws the next rows and moves into them (so the keyboard can walk the whole list); a row that has the
 * focus stays drawn, on its own, while the list scrolls.
 */
export function useWindowedRows(count: number, threshold: number = WINDOW_THRESHOLD) {
  const enabled = count > threshold;
  const host = useRef<HTMLElement | null>(null);
  /** A row a Tab is about to move into: drawn even before it has the focus. */
  const pinned = useRef<number | undefined>(undefined);
  const heights = useRef(new Map<number, number>());
  const [slice, setSliceState] = useState<Shown>(() => firstRows(count));

  const setHost = useCallback((el: HTMLElement | null) => {
    host.current = el;
  }, []);
  const estimate = (): number => {
    let total = 0;
    heights.current.forEach((h) => (total += h));
    return heights.current.size ? total / heights.current.size : ESTIMATED_ROW_PX;
  };
  const offsets = (): number[] => offsetsOf(count, (i) => heights.current.get(i), estimate());

  /** The row inside the host that has the keyboard focus, if any. */
  const focusedIndex = (): number | undefined => {
    const row = document.activeElement?.closest<HTMLElement>("[data-win-index]");
    return row && host.current?.contains(row) ? Number(row.dataset.winIndex) : undefined;
  };

  const setSlice = (next: WindowSlice) => setSliceState({ ...next, parts: partsFor(offsets(), next, pinned.current) });

  const settle = useCallback(() => {
    const el = host.current;
    if (!el || !enabled) return;
    // measure the rows drawn now
    let measured = false;
    el.querySelectorAll<HTMLElement>("[data-win-index]").forEach((row) => {
      const index = Number(row.dataset.winIndex);
      const height = row.getBoundingClientRect().height;
      if (height > 0 && Math.abs((heights.current.get(index) ?? -1) - height) > 0.5) {
        heights.current.set(index, height);
        measured = true;
      }
    });
    const parent = scrollParent(el);
    const view = parent ? parent.getBoundingClientRect() : { top: 0, bottom: window.innerHeight };
    const top = el.getBoundingClientRect().top;
    const all = offsets();
    const found = sliceFor(all, view.top - top, view.bottom - top, OVERSCAN_PX);
    const next = { ...found, parts: partsFor(all, found, pinned.current ?? focusedIndex()) };
    // a measurement or a moved pinned row needs a draw even when the window is the same
    setSliceState((prev) => (prev.start === next.start && prev.end === next.end && !measured && sameParts(prev.parts, next.parts) ? prev : next));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, count]);

  // After every render: measure what was drawn, and move the window if the measurements moved it.
  useLayoutEffect(() => {
    settle();
  });

  useEffect(() => {
    if (!enabled) return;
    let frame = 0;
    const later = () => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        settle();
      });
    };
    const onResize = () => {
      heights.current.clear(); // rows wrap differently at another width
      later();
    };
    const parent = scrollParent(host.current);
    window.addEventListener("scroll", later, { passive: true });
    window.addEventListener("resize", onResize);
    parent?.addEventListener("scroll", later, { passive: true });
    return () => {
      window.removeEventListener("scroll", later);
      window.removeEventListener("resize", onResize);
      parent?.removeEventListener("scroll", later);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [enabled, settle]);

  const shown: WindowSlice = enabled ? { start: Math.min(slice.start, Math.max(count - 1, 0)), end: Math.min(Math.max(slice.end, slice.start + 1), count) } : { start: 0, end: count };
  const parts: Part[] = enabled ? slice.parts.filter((p) => p.type === "spacer" || p.index < count) : [];

  /** Tab at the last control of the last drawn row (or Shift+Tab at the first of the first) draws the neighbouring
   *  rows and moves into them: the next control in the page would otherwise be past the whole list. */
  function handleKey(e: ReactKeyboardEvent<HTMLElement>) {
    if (!enabled || e.key !== "Tab" || e.ctrlKey || e.altKey || e.metaKey) return;
    const target = e.target as HTMLElement;
    const row = target.closest<HTMLElement>("[data-win-index]");
    if (!row || !host.current?.contains(row)) return;
    const index = Number(row.dataset.winIndex);
    const controls = [...row.querySelectorAll<HTMLElement>(FOCUSABLE)];
    const forward = !e.shiftKey;
    const atEdge = forward ? controls[controls.length - 1] === target && index === shown.end - 1 && shown.end < count
      : controls[0] === target && index === shown.start && shown.start > 0;
    if (!atEdge) return;
    e.preventDefault();
    const goTo = forward ? index + 1 : index - 1;
    pinned.current = goTo;
    flushSync(() => {
      setSlice(forward ? { start: shown.start, end: Math.min(count, shown.end + TAB_STEP_ROWS) } : { start: Math.max(0, shown.start - TAB_STEP_ROWS), end: shown.end });
    });
    const next = host.current?.querySelector<HTMLElement>(`[data-win-index="${goTo}"]`);
    const into = next ? [...next.querySelectorAll<HTMLElement>(FOCUSABLE)] : [];
    (forward ? into[0] : into[into.length - 1])?.focus();
    pinned.current = undefined;
  }

  const latestKey = useRef(handleKey);
  useEffect(() => {
    latestKey.current = handleKey;
  });
  const onKeyDown = useCallback((e: ReactKeyboardEvent<HTMLElement>) => latestKey.current(e), []);

  return {
    enabled,
    host: setHost,
    /** What to draw, in order: rows (by index) and spacers. Only when `enabled`. */
    parts,
    /** Spread on each drawn row. Nothing to add when the list is short. */
    rowProps: (index: number): { "data-win-index"?: number } => (enabled ? { "data-win-index": index } : {}),
    onKeyDown,
  };
}

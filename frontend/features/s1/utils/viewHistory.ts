"use client";

/**
 * Browser history for the workpaper's in-app screens.
 *
 * The workpaper is one Next.js page; its screens are React state, not routes. This hook mirrors
 * that state into `window.history` so the browser's Back and Forward buttons step through the
 * screens, and a reload lands on the same screen (`?view=evidence`, `?view=schedule&line=<key>`,
 * `?view=review&doc=<id>`). The Next.js router is not involved: only the standard History API is
 * used, with a state object of our own (`s1View`, `s1Index`).
 */

import { useCallback, useEffect, useRef, useState } from "react";

export type WorkpaperView =
  | { name: "dashboard" }
  | { name: "evidence" }
  | { name: "setup" }
  | { name: "requests" }
  | { name: "coverage" }
  | { name: "methodology" }
  | { name: "results"; lineKey?: string }
  | { name: "output" }
  | { name: "schedule"; lineKey: string }
  | { name: "extraction"; documentId: string; mode?: "snippet" | "manual"; nodeKey?: string; valueId?: string }
  | { name: "glossary"; previous: Exclude<WorkpaperView, { name: "glossary" }> };

const NAMES = [
  "dashboard", "evidence", "setup", "requests", "coverage", "methodology",
  "results", "output", "schedule", "extraction", "glossary",
] as const;

/** The `view=` value for each screen; the extraction review is `review` in the URL. */
const URL_NAME: Record<WorkpaperView["name"], string> = {
  dashboard: "dashboard", evidence: "evidence", setup: "setup", requests: "requests",
  coverage: "coverage", methodology: "methodology", results: "results", output: "output",
  schedule: "schedule", extraction: "review", glossary: "glossary",
};

/** Two views are the same screen when their plain data matches. */
export function sameView(a: WorkpaperView, b: WorkpaperView): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** The query string (without `?`) that identifies a view, so a reload can reopen it. */
export function viewToSearch(view: WorkpaperView): string {
  const p = new URLSearchParams();
  p.set("view", URL_NAME[view.name]);
  if (view.name === "schedule") p.set("line", view.lineKey);
  if (view.name === "results" && view.lineKey) p.set("line", view.lineKey);
  if (view.name === "extraction") {
    p.set("doc", view.documentId);
    if (view.valueId) p.set("value", view.valueId);
    if (view.nodeKey) p.set("node", view.nodeKey);
  }
  // A reload on the glossary opens the dashboard behind it (see parseViewFromSearch).
  return p.toString();
}

/** The view a query string names, or null when it names none (or an unusable one). */
export function parseViewFromSearch(search: string): WorkpaperView | null {
  const p = new URLSearchParams(search);
  const raw = p.get("view");
  if (!raw) return null;
  switch (raw) {
    case "schedule": {
      const line = p.get("line");
      return line ? { name: "schedule", lineKey: line } : null;
    }
    case "review": {
      const doc = p.get("doc");
      if (!doc) return null;
      return {
        name: "extraction",
        documentId: doc,
        mode: "snippet",
        nodeKey: p.get("node") ?? undefined,
        valueId: p.get("value") ?? undefined,
      };
    }
    case "results":
      return p.get("line") ? { name: "results", lineKey: p.get("line") as string } : { name: "results" };
    case "glossary":
      return { name: "glossary", previous: { name: "dashboard" } };
    case "dashboard": case "evidence": case "setup": case "requests":
    case "coverage": case "methodology": case "output":
      return { name: raw };
    default:
      return null;
  }
}

/** Reads a stored history state back into a view, if it is one of ours and well-formed. */
function viewFromState(state: unknown): { view: WorkpaperView; index: number } | null {
  if (typeof state !== "object" || state === null) return null;
  const s = state as { s1View?: unknown; s1Index?: unknown };
  const v = s.s1View as { name?: unknown } | undefined;
  if (!v || typeof v !== "object" || !(NAMES as readonly unknown[]).includes(v.name)) return null;
  return { view: s.s1View as WorkpaperView, index: typeof s.s1Index === "number" ? s.s1Index : 0 };
}

type Updater = WorkpaperView | ((current: WorkpaperView) => WorkpaperView);

/**
 * The active workpaper view, kept in step with browser history.
 *
 * - `navigate` shows a view and pushes a history entry (nothing when it is the same screen).
 * - `back(fallback)` goes to the previous screen the user came from when that is one of ours,
 *   otherwise navigates to `fallback`.
 * - Back/Forward (`popstate`) restore the stored view without pushing.
 * - The first view replaces the current entry (so the entry carries state) instead of pushing.
 */
export function useViewHistory(
  fallback: WorkpaperView = { name: "dashboard" }
): [WorkpaperView, (next: Updater) => void, (fallbackView: WorkpaperView) => void] {
  const [view, setView] = useState<WorkpaperView>(() => {
    if (typeof window === "undefined") return fallback;
    return (
      viewFromState(window.history.state)?.view ?? parseViewFromSearch(window.location.search) ?? fallback
    );
  });
  const viewRef = useRef(view);
  const indexRef = useRef(0);

  // First view: replace, not push. A reload keeps the stored index so Back still works.
  useEffect(() => {
    const stored = viewFromState(window.history.state);
    indexRef.current = stored?.index ?? 0;
    window.history.replaceState(
      { s1View: viewRef.current, s1Index: indexRef.current },
      "",
      `${window.location.pathname}?${viewToSearch(viewRef.current)}${window.location.hash}`
    );
    const onPop = (event: PopStateEvent) => {
      const restored =
        viewFromState(event.state) ??
        // An entry that is not ours (e.g. the page before the workpaper): fall back to the URL.
        (parseViewFromSearch(window.location.search) && {
          view: parseViewFromSearch(window.location.search) as WorkpaperView,
          index: 0,
        });
      if (!restored) return;
      indexRef.current = restored.index;
      viewRef.current = restored.view;
      setView(restored.view);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((next: Updater) => {
    const target = typeof next === "function" ? next(viewRef.current) : next;
    if (sameView(target, viewRef.current)) return;
    viewRef.current = target;
    indexRef.current += 1;
    window.history.pushState(
      { s1View: target, s1Index: indexRef.current },
      "",
      `${window.location.pathname}?${viewToSearch(target)}${window.location.hash}`
    );
    setView(target);
  }, []);

  const back = useCallback(
    (fallbackView: WorkpaperView) => {
      if (indexRef.current > 0) window.history.back();
      else navigate(fallbackView);
    },
    [navigate]
  );

  return [view, navigate, back];
}

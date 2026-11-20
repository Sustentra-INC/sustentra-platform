"use client";

/**
 * Browser history for the workpaper's in-app screens.
 *
 * The workpaper is one Next.js page; its screens are React state, not routes. This hook mirrors
 * that state into `window.history` so the browser's Back and Forward buttons step through the
 * screens, and a reload lands on the same screen (`?view=evidence`, `?view=schedule&line=<key>`,
 * `?view=review&doc=<id>`). Every entry is scoped to an engagement (`?e=<id>`, `s1Engagement`):
 * Back never shows a screen from another engagement. The Next.js router is not involved: only the
 * standard History API is used, with a state object of our own.
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
  | {
      name: "extraction";
      documentId: string;
      mode?: "snippet" | "manual";
      nodeKey?: string;
      valueId?: string;
      /** Opened from a methodology source: the cited page, the methodology field and its list entry whose quote is highlighted. */
      page?: number;
      field?: string;
      entry?: number;
    }
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

/** The query string (without `?`) that identifies a view in an engagement, so a reload can reopen it. */
export function viewToSearch(view: WorkpaperView, engagementId = ""): string {
  const p = new URLSearchParams();
  p.set("view", URL_NAME[view.name]);
  if (engagementId) p.set("e", engagementId);
  if (view.name === "schedule") p.set("line", view.lineKey);
  if (view.name === "results" && view.lineKey) p.set("line", view.lineKey);
  if (view.name === "extraction") {
    p.set("doc", view.documentId);
    if (view.valueId) p.set("value", view.valueId);
    if (view.nodeKey) p.set("node", view.nodeKey);
    if (view.page) p.set("page", String(view.page));
    if (view.field) p.set("field", view.field);
    if (view.field && view.entry !== undefined) p.set("entry", String(view.entry));
  }
  // A reload on the glossary opens the dashboard behind it (see parseViewFromSearch).
  return p.toString();
}

/** `{key: n}` for a whole number of at least `min` in the query, else nothing. */
function positive<K extends string>(raw: string | null, key: K, min = 1): { [P in K]?: number } {
  const n = raw !== null && /^\d{1,6}$/.test(raw) ? Number(raw) : NaN;
  return (Number.isInteger(n) && n >= min ? { [key]: n } : {}) as { [P in K]?: number };
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
        ...positive(p.get("page"), "page"),
        ...(p.get("field") ? { field: p.get("field") as string, ...positive(p.get("entry"), "entry", 0) } : {}),
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

/** The engagement a URL names (`?e=`), if any. */
export function engagementFromSearch(search: string): string | null {
  return new URLSearchParams(search).get("e") || null;
}

/** What the "Back to ..." link calls a screen. */
export function viewLabel(view: WorkpaperView): string {
  switch (view.name) {
    case "dashboard": return "dashboard";
    case "evidence": return "evidence";
    case "schedule": return "data point review";
    case "extraction": return "document review";
    case "results": return "results";
    case "setup": return "setup";
    case "requests": case "coverage": return "coverage and requests";
    case "methodology": return "methodology";
    case "output": return "output";
    case "glossary": return "glossary";
  }
}

interface Stored {
  view: WorkpaperView;
  index: number;
  engagement: string | null;
  previous: WorkpaperView | null;
}

function isView(v: unknown): v is WorkpaperView {
  return typeof v === "object" && v !== null && (NAMES as readonly unknown[]).includes((v as { name?: unknown }).name);
}

/** Reads a stored history state back into a view, if it is one of ours and well-formed. */
function viewFromState(state: unknown): Stored | null {
  if (typeof state !== "object" || state === null) return null;
  const s = state as { s1View?: unknown; s1Index?: unknown; s1Engagement?: unknown; s1Prev?: unknown };
  if (!isView(s.s1View)) return null;
  return {
    view: s.s1View,
    index: typeof s.s1Index === "number" ? s.s1Index : 0,
    engagement: typeof s.s1Engagement === "string" && s.s1Engagement ? s.s1Engagement : null,
    previous: isView(s.s1Prev) ? s.s1Prev : null,
  };
}

type Updater = WorkpaperView | ((current: WorkpaperView) => WorkpaperView);

export interface ViewHistory {
  view: WorkpaperView;
  /** Shows a view and pushes a history entry (nothing when it is the same screen). */
  navigate: (next: Updater) => void;
  /** Shows a view in place of the current entry (no new entry). */
  replaceView: (next: WorkpaperView) => void;
  /** Goes to the screen the user came from if it is one of ours, otherwise navigates to `fallback`. */
  back: (fallback: WorkpaperView) => void;
  /** The screen the back link goes to, or null when there is none of ours (it uses the fallback). */
  previous: WorkpaperView | null;
  /** The engagement the page was opened for (`?e=`), before the app had loaded any. */
  requestedEngagement: string | null;
}

/**
 * The active workpaper view, kept in step with browser history.
 *
 * - The first view replaces the current entry (so it carries state) instead of pushing.
 * - `popstate` restores the stored view without pushing. An entry that belongs to another
 *   engagement than the open one is never shown: it is replaced by the open engagement's
 *   dashboard (the simplest safe behaviour; the user stays in the engagement they chose).
 * - Switching engagement keeps the current screen, stamps the entry with the new engagement and
 *   forgets the earlier entries as back targets.
 * - On load, `?e=` that differs from the engagement the app ends up with resets to the dashboard.
 */
export function useViewHistory(engagementId: string): ViewHistory {
  const [initial] = useState(() => {
    const fromState = typeof window === "undefined" ? null : viewFromState(window.history.state);
    const search = typeof window === "undefined" ? "" : window.location.search;
    return {
      view: fromState?.view ?? parseViewFromSearch(search) ?? ({ name: "dashboard" } as WorkpaperView),
      previous: fromState?.previous ?? null,
      requested: fromState?.engagement ?? engagementFromSearch(search),
    };
  });
  const [view, setView] = useState<WorkpaperView>(initial.view);
  const [previous, setPrevious] = useState<WorkpaperView | null>(initial.previous);
  const viewRef = useRef(view);
  const prevRef = useRef(previous);
  const indexRef = useRef(0);
  const engagementRef = useRef("");
  const settled = useRef(false);

  const commit = useCallback((mode: "push" | "replace", target: WorkpaperView, prev: WorkpaperView | null) => {
    const e = engagementRef.current || (initial.requested ?? "");
    const state = { s1View: target, s1Index: indexRef.current, s1Engagement: engagementRef.current, s1Prev: prev };
    const url = `${window.location.pathname}?${viewToSearch(target, e)}${window.location.hash}`;
    if (mode === "push") window.history.pushState(state, "", url);
    else window.history.replaceState(state, "", url);
    viewRef.current = target;
    prevRef.current = prev;
    setView(target);
    setPrevious(prev);
  }, [initial.requested]);

  // The first view replaces, not push. A reload keeps the stored index so Back still works.
  useEffect(() => {
    const stored = viewFromState(window.history.state);
    indexRef.current = stored?.index ?? 0;
    commit("replace", viewRef.current, prevRef.current);
    const onPop = (event: PopStateEvent) => {
      const restored = viewFromState(event.state);
      const fromUrl = restored ? null : parseViewFromSearch(window.location.search);
      if (!restored && !fromUrl) return;
      const target = restored?.view ?? (fromUrl as WorkpaperView);
      const entryEngagement = restored?.engagement ?? engagementFromSearch(window.location.search);
      const open = engagementRef.current;
      if (open && entryEngagement && entryEngagement !== open) {
        indexRef.current = 0;
        commit("replace", { name: "dashboard" }, null);
        return;
      }
      indexRef.current = restored?.index ?? 0;
      // Restoring: the entry already holds this state, so only the React state follows.
      viewRef.current = target;
      prevRef.current = restored?.previous ?? null;
      setView(target);
      setPrevious(prevRef.current);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [commit]);

  // The app's engagement: loaded after mount in backend mode, and it can change.
  useEffect(() => {
    if (!engagementId) return;
    const wanted = initial.requested;
    const first = !settled.current;
    settled.current = true;
    engagementRef.current = engagementId;
    if (first && wanted && wanted !== engagementId) {
      // The page was opened for an engagement this user can't open: start at the dashboard.
      indexRef.current = 0;
      commit("replace", { name: "dashboard" }, null);
      return;
    }
    if (!first) indexRef.current = 0; // switched: earlier entries are another engagement's
    commit("replace", viewRef.current, first ? prevRef.current : null);
  }, [engagementId, commit, initial.requested]);

  const navigate = useCallback(
    (next: Updater) => {
      const target = typeof next === "function" ? next(viewRef.current) : next;
      if (sameView(target, viewRef.current)) return;
      const from = viewRef.current;
      indexRef.current += 1;
      commit("push", target, from);
    },
    [commit]
  );

  const replaceView = useCallback(
    (next: WorkpaperView) => {
      if (sameView(next, viewRef.current)) return;
      commit("replace", next, prevRef.current);
    },
    [commit]
  );

  const back = useCallback(
    (fallback: WorkpaperView) => {
      if (indexRef.current > 0 && prevRef.current) window.history.back();
      else navigate(fallback);
    },
    [navigate]
  );

  return { view, navigate, replaceView, back, previous, requestedEngagement: initial.requested };
}

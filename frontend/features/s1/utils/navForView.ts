import type { NavKey } from "../components/S1Chrome";

/** A view as the workpaper tracks it; an overlay (the glossary) remembers the view it was opened from. */
export interface NavView {
  name: string;
  previous?: NavView;
}

const NAV_FOR_VIEW: Record<string, NavKey> = {
  dashboard: "dashboard",
  setup: "setup",
  requests: "requests",
  coverage: "requests",
  methodology: "methodology",
  results: "results",
  output: "output",
  schedule: "evidence",
  evidence: "evidence",
  // Extraction review is opened from Evidence, so Evidence stays lit.
  extraction: "evidence",
};

/** Which sidebar item is current. An overlay view with no entry of its own (the glossary) keeps the
 *  highlight of the view it was opened from; anything else unknown falls back to Evidence. */
export function navForView(view: NavView): NavKey {
  const own = NAV_FOR_VIEW[view.name];
  if (own) return own;
  if (view.previous) return navForView(view.previous);
  return "evidence";
}

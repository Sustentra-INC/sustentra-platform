// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { parseViewFromSearch, useViewHistory, viewToSearch } from "../utils/viewHistory";

/** jsdom has no real back stack for our purposes, so keep our own and replay popstate. */
function installHistory() {
  const stack: { state: unknown; url: string }[] = [{ state: null, url: window.location.href }];
  let at = 0;
  const fire = () => {
    const entry = stack[at];
    window.history.replaceState(entry.state, "", entry.url);
    window.dispatchEvent(new PopStateEvent("popstate", { state: entry.state }));
  };
  window.history.pushState = (state: unknown, _t: string, url?: string | URL | null) => {
    stack.splice(at + 1);
    stack.push({ state, url: String(url) });
    at += 1;
    Object.getPrototypeOf(window.history).replaceState.call(window.history, state, "", url);
  };
  const realReplace = Object.getPrototypeOf(window.history).replaceState;
  window.history.replaceState = (state: unknown, _t: string, url?: string | URL | null) => {
    stack[at] = { state, url: String(url ?? stack[at].url) };
    realReplace.call(window.history, state, "", url);
  };
  window.history.back = () => {
    if (at === 0) return;
    at -= 1;
    fire();
  };
  return { stack, pushes: () => stack.length };
}

describe("workpaper browser history", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("steps back through evidence, schedule and review", () => {
    const h = installHistory();
    const { result } = renderHook(() => useViewHistory());
    expect(result.current[0].name).toBe("dashboard");
    expect(h.stack).toHaveLength(1); // first view replaces, never pushes

    act(() => result.current[1]({ name: "evidence" }));
    act(() => result.current[1]({ name: "schedule", lineKey: "scope1" }));
    act(() => result.current[1]({ name: "extraction", documentId: "DOC-1", mode: "snippet" }));
    expect(h.stack).toHaveLength(4);
    expect(window.location.search).toBe("?view=review&doc=DOC-1");

    const states = h.stack.map((e) => e.state);
    for (const [i, name] of [[2, "schedule"], [1, "evidence"], [0, "dashboard"]] as const) {
      act(() => {
        window.dispatchEvent(new PopStateEvent("popstate", { state: states[i] }));
      });
      expect(result.current[0].name).toBe(name);
    }
    expect(h.stack).toHaveLength(4); // popstate never pushes
  });

  it("does not push a duplicate entry for the same view", () => {
    const h = installHistory();
    const { result } = renderHook(() => useViewHistory());
    act(() => result.current[1]({ name: "evidence" }));
    act(() => result.current[1]({ name: "evidence" }));
    expect(h.stack).toHaveLength(2);
  });

  it("the back link returns to the screen the user came from", () => {
    installHistory();
    const { result } = renderHook(() => useViewHistory());
    act(() => result.current[1]({ name: "evidence" }));
    act(() => result.current[1]({ name: "schedule", lineKey: "scope1" }));
    act(() => result.current[1]({ name: "extraction", documentId: "DOC-1" }));
    act(() => result.current[2]({ name: "evidence" }));
    expect(result.current[0]).toEqual({ name: "schedule", lineKey: "scope1" });
  });

  it("the back link falls back when there is no earlier screen of ours", () => {
    installHistory();
    window.history.replaceState(null, "", "/?view=review&doc=DOC-9");
    const { result } = renderHook(() => useViewHistory());
    expect(result.current[0].name).toBe("extraction");
    act(() => result.current[2]({ name: "evidence" }));
    expect(result.current[0].name).toBe("evidence");
  });

  it("a reload with ?view=evidence opens Evidence", () => {
    window.history.replaceState(null, "", "/?view=evidence");
    const { result } = renderHook(() => useViewHistory());
    expect(result.current[0]).toEqual({ name: "evidence" });
  });

  it("round-trips the URL of schedule and review views", () => {
    for (const view of [
      { name: "schedule", lineKey: "a b" } as const,
      { name: "extraction", documentId: "D", mode: "snippet", valueId: "V", nodeKey: "F:x|T:y" } as const,
    ]) {
      expect(parseViewFromSearch(viewToSearch(view))).toEqual(view);
    }
    expect(parseViewFromSearch("?view=nonsense")).toBeNull();
  });
});

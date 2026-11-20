// @vitest-environment jsdom
import { act, render, renderHook, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { S1WorkpaperApp } from "../pages/S1WorkpaperApp";
import { parseViewFromSearch, useViewHistory, viewLabel, viewToSearch } from "../utils/viewHistory";

/** jsdom has no usable back stack here, so keep our own and replay popstate. */
function installHistory() {
  const proto = Object.getPrototypeOf(window.history);
  const realReplace = proto.replaceState;
  const realPush = proto.pushState;
  const stack: { state: unknown; url: string }[] = [{ state: null, url: window.location.href }];
  let at = 0;
  window.history.pushState = (state: unknown, _t: string, url?: string | URL | null) => {
    stack.splice(at + 1);
    stack.push({ state, url: String(url) });
    at += 1;
    realPush.call(window.history, state, "", url);
  };
  window.history.replaceState = (state: unknown, _t: string, url?: string | URL | null) => {
    stack[at] = { state, url: String(url ?? stack[at].url) };
    realReplace.call(window.history, state, "", url);
  };
  window.history.back = () => {
    if (at === 0) return;
    at -= 1;
    realReplace.call(window.history, stack[at].state, "", stack[at].url);
    window.dispatchEvent(new PopStateEvent("popstate", { state: stack[at].state }));
  };
  /** Fire popstate for the entry at `index`, as the browser does when the user steps to it. */
  const popTo = (index: number) => {
    at = index;
    realReplace.call(window.history, stack[at].state, "", stack[at].url);
    window.dispatchEvent(new PopStateEvent("popstate", { state: stack[at].state }));
  };
  return { stack, popTo };
}

describe("workpaper browser history", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("steps back through evidence, schedule and review", () => {
    const h = installHistory();
    const { result } = renderHook(() => useViewHistory("E1"));
    expect(result.current.view.name).toBe("dashboard");
    expect(h.stack).toHaveLength(1); // first view replaces, never pushes

    act(() => result.current.navigate({ name: "evidence" }));
    act(() => result.current.navigate({ name: "schedule", lineKey: "scope1" }));
    act(() => result.current.navigate({ name: "extraction", documentId: "DOC-1", mode: "snippet" }));
    expect(h.stack).toHaveLength(4);
    expect(window.location.search).toBe("?view=review&e=E1&doc=DOC-1");

    for (const [i, name] of [[2, "schedule"], [1, "evidence"], [0, "dashboard"]] as const) {
      act(() => h.popTo(i));
      expect(result.current.view.name).toBe(name);
    }
    expect(h.stack).toHaveLength(4); // popstate never pushes
  });

  it("does not push a duplicate entry for the same view", () => {
    const h = installHistory();
    const { result } = renderHook(() => useViewHistory("E1"));
    act(() => result.current.navigate({ name: "evidence" }));
    act(() => result.current.navigate({ name: "evidence" }));
    expect(h.stack).toHaveLength(2);
  });

  it("the back link returns to the screen the user came from, and says so", () => {
    installHistory();
    const { result } = renderHook(() => useViewHistory("E1"));
    act(() => result.current.navigate({ name: "evidence" }));
    act(() => result.current.navigate({ name: "schedule", lineKey: "scope1" }));
    act(() => result.current.navigate({ name: "extraction", documentId: "DOC-1" }));
    expect(viewLabel(result.current.previous!)).toBe("data point review");
    act(() => result.current.back({ name: "evidence" }));
    expect(result.current.view).toEqual({ name: "schedule", lineKey: "scope1" });
    expect(viewLabel(result.current.previous!)).toBe("evidence");
  });

  it("the label follows the previous view: a review opened from the dashboard says dashboard", () => {
    installHistory();
    const { result } = renderHook(() => useViewHistory("E1"));
    act(() => result.current.navigate({ name: "extraction", documentId: "DOC-1" }));
    expect(viewLabel(result.current.previous!)).toBe("dashboard");
    act(() => result.current.back({ name: "evidence" }));
    expect(result.current.view.name).toBe("dashboard");
  });

  it("with no earlier screen of ours there is no previous, and back uses the fallback", () => {
    installHistory();
    window.history.replaceState(null, "", "/?view=review&doc=DOC-9");
    const { result } = renderHook(() => useViewHistory("E1"));
    expect(result.current.view.name).toBe("extraction");
    expect(result.current.previous).toBeNull();
    act(() => result.current.back({ name: "evidence" }));
    expect(result.current.view.name).toBe("evidence");
  });

  it("a reload with ?view=evidence opens Evidence", () => {
    window.history.replaceState(null, "", "/?view=evidence");
    const { result } = renderHook(() => useViewHistory("E1"));
    expect(result.current.view).toEqual({ name: "evidence" });
  });

  it("an engagement switch then Back never shows the old engagement's screen", () => {
    const h = installHistory();
    const { result, rerender } = renderHook(({ id }) => useViewHistory(id), { initialProps: { id: "E1" } });
    act(() => result.current.navigate({ name: "evidence" }));
    act(() => result.current.navigate({ name: "schedule", lineKey: "scope1" }));

    rerender({ id: "E2" }); // the user switches engagement; the screen stays
    expect(result.current.view.name).toBe("schedule");
    expect(window.location.search).toContain("e=E2");
    expect(result.current.previous).toBeNull(); // no back target of ours

    // The browser's Back lands on E1's evidence entry: it is replaced by E2's dashboard.
    act(() => h.popTo(1));
    expect(result.current.view).toEqual({ name: "dashboard" });
    expect(window.location.search).toBe("?view=dashboard&e=E2");
    // Forward to the entry the user switched on: it was stamped E2, so it is fine to show.
    act(() => h.popTo(2));
    expect(result.current.view.name).toBe("schedule");
  });

  it("a URL for an engagement the user can't open resets to the dashboard", () => {
    window.history.replaceState(null, "", "/?view=schedule&e=OTHER&line=scope1");
    const { result } = renderHook(() => useViewHistory("E1"));
    expect(result.current.requestedEngagement).toBe("OTHER");
    expect(result.current.view).toEqual({ name: "dashboard" });
    expect(window.location.search).toBe("?view=dashboard&e=E1");
  });

  it("a URL for the open engagement keeps its screen", () => {
    window.history.replaceState(null, "", "/?view=evidence&e=E1");
    const { result } = renderHook(() => useViewHistory("E1"));
    expect(result.current.view).toEqual({ name: "evidence" });
  });

  it("round-trips the URL of schedule and review views", () => {
    for (const view of [
      { name: "schedule", lineKey: "a b" } as const,
      { name: "extraction", documentId: "D", mode: "snippet", valueId: "V", nodeKey: "F:x|T:y" } as const,
    ]) {
      expect(parseViewFromSearch(viewToSearch(view, "E1"))).toEqual(view);
    }
    expect(parseViewFromSearch("?view=nonsense")).toBeNull();
  });
});

describe("a reload that names a document the engagement doesn't have", () => {
  it("opens Evidence with a plain notice", async () => {
    vi.stubEnv("NEXT_PUBLIC_S1_DATA_MODE", "fixture");
    window.localStorage.setItem("sustentra-demo-signedin", "1");
    window.history.replaceState(null, "", "/?view=review&doc=NO-SUCH-DOC");
    render(<S1WorkpaperApp />);
    expect(await screen.findByText("That document is no longer in this engagement.")).toBeTruthy();
    expect(window.location.search).toContain("view=evidence");
    vi.unstubAllEnvs();
  });
});

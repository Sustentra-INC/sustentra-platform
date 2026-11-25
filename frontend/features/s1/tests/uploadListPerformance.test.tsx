/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, render } from "@testing-library/react";

import { UploadDialog, type UploadTask } from "../components/UploadDialog";

const tasks = (n: number): UploadTask[] =>
  Array.from({ length: n }, (_, i) => ({
    id: `t${i}`,
    filename: `file-${i}.pdf`,
    path: `Plant ${i % 20}/2025/file-${i}.pdf`,
    size: 1000,
    progress: 0,
    stage: i === 0 ? ("uploading" as const) : ("waiting" as const),
  }));

// What the app does on a progress tick: patchTask maps the whole array, replacing one task.
const tick = (list: UploadTask[], id: string, progress: number) =>
  list.map((t) => (t.id === id ? { ...t, progress } : t));

function dialog(list: UploadTask[]) {
  return (
    <UploadDialog onClose={vi.fn()} onUploadFiles={vi.fn()} batch={[]} tasks={list} onOpenWorkspace={vi.fn()} />
  );
}

describe("a long upload list stays responsive", () => {
  it.each([1000, 4000])("%i rows: one progress tick costs a few milliseconds, not a redraw of every row", (n) => {
    let list = tasks(n);
    const { rerender } = render(dialog(list));
    expect(document.querySelectorAll(".s1-upq__row")).toHaveLength(n);

    const patchStart = performance.now();
    for (let i = 1; i <= 100; i++) list = tick(list, "t0", i / 100);
    const patchMs = (performance.now() - patchStart) / 100;

    const start = performance.now();
    for (let i = 1; i <= 20; i++) {
      list = tick(list, "t0", Math.min(1, 0.5 + i / 50));
      act(() => rerender(dialog(list)));
    }
    const perTick = (performance.now() - start) / 20;
    console.info(`${n} rows: patch ${patchMs.toFixed(3)} ms, patch + render ${perTick.toFixed(1)} ms per tick`);
    // Ticks are throttled to one per 150 ms, so even 100 ms here would be well inside the frame budget
    // of the work the page does between ticks; the bound is generous to stay stable on a slow runner.
    expect(patchMs).toBeLessThan(5);
    expect(perTick).toBeLessThan(400);
  });

  it("shows the sent name in a row's title when it differs from the path's last part", () => {
    render(
      dialog([
        { id: "a", filename: "Plant A - bill.pdf", path: "Plant A/bill.pdf", size: 1, progress: 0, stage: "waiting" },
        { id: "b", filename: "plain.pdf", path: "x/plain.pdf", size: 1, progress: 0, stage: "waiting" },
      ])
    );
    const titles = Array.from(document.querySelectorAll("[title]"), (e) => e.getAttribute("title"));
    expect(titles).toContain("Plant A/bill.pdf\nSent as: Plant A - bill.pdf");
    expect(titles).toContain("x/plain.pdf");
  });
});

/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, render } from "@testing-library/react";

// Each row draws its name once per redraw: counting names counts redrawn rows.
const drawn = vi.hoisted(() => ({ rows: 0 }));
vi.mock("../components/BreakableName", async (original) => {
  const real = await original<typeof import("../components/BreakableName")>();
  return {
    ...real,
    BreakableName: (props: Parameters<typeof real.BreakableName>[0]) => {
      drawn.rows += 1;
      return real.BreakableName(props);
    },
  };
});

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
  it("redraws only the row that moved on a progress tick, with 1,000 rows", () => {
    let list = tasks(1000);
    const { rerender } = render(dialog(list));
    expect(document.querySelectorAll(".s1-upq__row")).toHaveLength(1000);
    drawn.rows = 0;
    for (let i = 1; i <= 10; i++) {
      list = tick(list, "t0", i / 20);
      act(() => rerender(dialog(list)));
    }
    expect(drawn.rows).toBe(10);
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

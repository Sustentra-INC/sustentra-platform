/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { UploadDialog, uploadTasksForItems, type UploadTask } from "../components/UploadDialog";
import type { UploadItem } from "../utils/expandUploads";
import { pickFromDrop, pickFromFileList } from "../utils/uploadSources";

const task = (over: Partial<UploadTask>): UploadTask => ({ id: "t", filename: "jan.pdf", size: 10, progress: 0, stage: "waiting", ...over });

function dialog(props: Partial<React.ComponentProps<typeof UploadDialog>> = {}) {
  return render(<UploadDialog onClose={vi.fn()} onUploadFiles={vi.fn()} batch={[]} onOpenWorkspace={vi.fn()} {...props} />);
}

describe("upload dialog: folders and zips", () => {
  it("offers a keyboard-reachable folder picker and says zips and folders are fine", () => {
    dialog();
    const input = document.querySelectorAll('input[type="file"]')[1] as HTMLInputElement;
    expect(input).toHaveAttribute("webkitdirectory");
    expect(screen.getByText(/Choose a folder/)).toBeInTheDocument();
    expect(screen.getByText(/Zip files too/)).toBeInTheDocument();
  });

  it("hands a chosen folder to the upload with each file's path", () => {
    const onUploadFiles = vi.fn();
    dialog({ onUploadFiles });
    const input = document.querySelectorAll('input[type="file"]')[1] as HTMLInputElement;
    const f = new File(["x"], "jan.pdf");
    Object.defineProperty(f, "webkitRelativePath", { value: "Plant A/2025/jan.pdf" });
    fireEvent.change(input, { target: { files: [f] } });
    expect(onUploadFiles).toHaveBeenCalledWith({ sources: [{ file: f, path: "Plant A/2025/jan.pdf" }], refused: [] });
  });

  it("shows the path of each file, the summary, and the reason for what can't be read", () => {
    const items: UploadItem[] = [
      { path: "Plant A/2025/jan.pdf", name: "jan.pdf", size: 10, open: async () => new File(["x"], "jan.pdf") },
      { path: "Plant A/2025/x.xyz", name: "x.xyz", size: 5, reason: "x.xyz can't be read here." },
    ];
    const tasks = uploadTasksForItems(items, "b");
    dialog({ tasks, summaryLines: ["2 files found in Evidence.zip, 1 can't be read"] });
    expect(screen.getByText("2 files found in Evidence.zip, 1 can't be read")).toBeInTheDocument();
    expect(screen.getByTitle("Plant A/2025/jan.pdf")).toBeInTheDocument();
    expect(screen.getByText("x.xyz can't be read here.")).toBeInTheDocument();
    expect(screen.getByText("Not uploaded")).toBeInTheDocument();
  });

  it("a plain file keeps showing just its name", () => {
    const [t] = uploadTasksForItems([{ path: "bill.pdf", name: "bill.pdf", size: 1, open: async () => new File(["x"], "bill.pdf") }], "b");
    expect(t.path).toBeUndefined();
  });

  it("says what is being unpacked and lets the user cancel", () => {
    const onCancelUpload = vi.fn();
    dialog({ unpackNote: "Looking through Evidence.zip…", onCancelUpload });
    expect(screen.getByText("Looking through Evidence.zip…")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancelUpload).toHaveBeenCalled();
  });

  it("offers to try only the files that failed because of a hiccup", () => {
    const onRetryFailed = vi.fn();
    dialog({
      tasks: [
        task({ id: "a", stage: "done", progress: 1 }),
        task({ id: "b", stage: "not_uploaded", error: "The upload was interrupted.", retryable: true }),
        task({ id: "c", stage: "not_uploaded", error: "Empty." }),
      ],
      onRetryFailed,
    });
    fireEvent.click(screen.getByRole("button", { name: /Try the 1 file that didn’t send again/ }));
    expect(onRetryFailed).toHaveBeenCalled();
  });

  it("announces progress in one live line, not the whole list", () => {
    dialog({ tasks: [task({ id: "a" })] });
    expect(screen.getByRole("progressbar", { name: "Upload progress" })).toBeInTheDocument();
    expect(document.querySelector(".s1-upq")).not.toHaveAttribute("aria-live");
    expect(document.querySelector(".s1-upq__head")).toHaveAttribute("aria-live", "polite");
  });

  it("makes a long list a focusable scroll area", () => {
    dialog({ tasks: Array.from({ length: 12 }, (_, i) => task({ id: `t${i}`, filename: `f${i}.pdf` })) });
    expect(screen.getByRole("list", { name: "Files in this upload" })).toHaveAttribute("tabindex", "0");
  });
});

// A fake of the browser's directory entries: readEntries gives 100 at a time, then none.
type Node = { name: string; kids?: Node[]; body?: string };
function entryOf(node: Node): unknown {
  if (!node.kids) return { isFile: true, isDirectory: false, name: node.name, file: (ok: (f: File) => void) => ok(new File([node.body ?? "x"], node.name)) };
  return {
    isFile: false,
    isDirectory: true,
    name: node.name,
    createReader: () => {
      let at = 0;
      return {
        readEntries: (ok: (e: unknown[]) => void) => {
          const batch = node.kids!.slice(at, at + 100).map(entryOf);
          at += 100;
          ok(batch);
        },
      };
    },
  };
}
const dropOf = (nodes: Node[]) =>
  ({
    files: [],
    items: nodes.map((n) => ({ kind: "file", webkitGetAsEntry: () => entryOf(n) })),
  }) as unknown as DataTransfer;

describe("dropping folders", () => {
  it("walks nested folders and reads every page of 100 entries", async () => {
    const many = Array.from({ length: 250 }, (_, i) => ({ name: `f${i}.pdf` }));
    const pick = await pickFromDrop(dropOf([{ name: "Evidence", kids: [{ name: "Plant A", kids: [{ name: "jan.pdf" }] }, ...many] }, { name: "loose.csv" }]));
    expect(pick.sources).toHaveLength(252);
    expect(pick.sources[0].path).toBe("Evidence/Plant A/jan.pdf");
    expect(pick.sources[1].path).toBe("Evidence/f0.pdf");
    expect(pick.sources.at(-1)?.path).toBe("loose.csv");
    expect(pick.refused).toEqual([]);
  });

  it("refuses a folder far past the limit instead of walking it all", async () => {
    const huge = Array.from({ length: 5200 }, (_, i) => ({ name: `f${i}.pdf` }));
    const pick = await pickFromDrop(dropOf([{ name: "Huge", kids: huge }, { name: "ok.pdf" }]));
    expect(pick.refused).toEqual([{ name: "Huge", reason: expect.stringMatching(/more than 1,000 files/) }]);
    expect(pick.sources.map((s) => s.path)).toEqual(["ok.pdf"]);
  });

  it("falls back to the plain file list when the browser gives no entries", async () => {
    const f = new File(["x"], "a.pdf");
    const pick = await pickFromDrop({ files: [f], items: [] } as unknown as DataTransfer);
    expect(pick).toEqual(pickFromFileList([f]));
  });
});

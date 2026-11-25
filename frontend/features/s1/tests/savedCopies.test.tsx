/* @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pages = vi.hoisted(() => ({ list: [] as unknown[], calls: [] as string[], fail: false }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn((path: string) => {
    pages.calls.push(path);
    if (pages.fail) return Promise.reject(new Error("Server error"));
    const limit = Number(/limit=(\d+)/.exec(path)?.[1] ?? 20);
    return Promise.resolve({ items: pages.list.slice(0, limit), total: pages.list.length, limit, offset: 0 });
  }),
}));

import { SavedCopies } from "../components/SavedCopies";
import { LiveOutputForTest } from "./savedCopiesHarness";

const copy = (n: number, extra: Record<string, unknown> = {}) => ({
  id: `copy-${n}`, created_at: `2026-11-${String(10 + n).padStart(2, "0")}T15:04:00Z`, prepared_by: `person${n}@firm.test`,
  file_name: "x.xlsx", size_bytes: 20_480 + n, sha256: `${n}`.repeat(64).slice(0, 64), app_version: "v", downloads: 1, ...extra,
});

const onDownload = vi.fn();

beforeEach(() => {
  onDownload.mockClear();
  pages.list = [];
  pages.calls = [];
  pages.fail = false;
});

describe("Saved copies on Output", () => {
  it("says so in one line when nothing is saved yet", async () => {
    render(<SavedCopies engagementId="E1" refreshKey={0} busyId={null} onDownload={onDownload} />);
    expect(await screen.findByText("Each workpaper you download is saved here.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("lists date and time, who, size, a 12-character fingerprint with the full one in its title, and a download link", async () => {
    pages.list = [copy(2), copy(1)];
    render(<SavedCopies engagementId="E 1" refreshKey={0} busyId={null} onDownload={onDownload} />);
    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(3); // header + 2
    const first = within(rows[1]);
    expect(first.getByText("person2@firm.test")).toBeTruthy();
    expect(first.getByText("20 KB")).toBeTruthy();
    const code = first.getByText("222222222222");
    expect(code.getAttribute("title")).toBe("2".repeat(64));
    fireEvent.click(first.getByRole("button", { name: /Download/ }));
    expect(onDownload).toHaveBeenCalledWith("copy-2", "/api/v1/engagements/E%201/workpaper-copies/copy-2/download");
    expect(screen.getByText("Fingerprint").getAttribute("title")).toMatch(/identifies this exact file/);
    expect(pages.calls[0]).toBe("/engagements/E%201/workpaper-copies?limit=3&offset=0");
  });

  it("shows the newest three and offers the older ones", async () => {
    pages.list = Array.from({ length: 12 }, (_, n) => copy(n));
    render(<SavedCopies engagementId="E1" refreshKey={0} busyId={null} onDownload={onDownload} />);
    fireEvent.click(await screen.findByRole("button", { name: "Show older copies (9 more)" }));
    await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(13));
    expect(screen.queryByRole("button", { name: /Show older/ })).toBeNull();
  });

  it("never asks for more than the API gives, and says so", async () => {
    pages.list = Array.from({ length: 130 }, (_, n) => copy(n));
    render(<SavedCopies engagementId="E1" refreshKey={0} busyId={null} onDownload={onDownload} />);
    for (let n = 0; n < 10; n++) fireEvent.click(await screen.findByRole("button", { name: /Show older/ }));
    expect(await screen.findByText("The newest 100 are shown.")).toBeTruthy();
    expect(Math.max(...pages.calls.map((c) => Number(/limit=(\d+)/.exec(c)?.[1])))).toBe(100);
  });

  it("says plainly when the list cannot be loaded", async () => {
    pages.fail = true;
    render(<SavedCopies engagementId="E1" refreshKey={0} busyId={null} onDownload={onDownload} />);
    expect(await screen.findByText(/Could not load the saved copies\. Server error/)).toBeTruthy();
  });

  it("shows nothing on the demo site, which keeps no copies", () => {
    render(<LiveOutputForTest demo />);
    expect(screen.queryByRole("region", { name: "Saved copies" })).toBeNull();
    expect(pages.calls).toHaveLength(0);
  });
});

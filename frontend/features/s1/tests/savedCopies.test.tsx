/* @vitest-environment jsdom */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

beforeEach(() => {
  pages.list = [];
  pages.calls = [];
  pages.fail = false;
});
afterEach(() => vi.useRealTimers());

describe("Saved copies on Output", () => {
  it("says so in one line when nothing is saved yet", async () => {
    render(<SavedCopies engagementId="E1" refreshKey={0} />);
    expect(await screen.findByText("Each workpaper you download is saved here.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("lists date and time, who, size, a 12-character fingerprint with the full one in its title, and a download link", async () => {
    pages.list = [copy(2), copy(1)];
    render(<SavedCopies engagementId="E 1" refreshKey={0} />);
    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(3); // header + 2
    const first = within(rows[1]);
    expect(first.getByText("person2@firm.test")).toBeTruthy();
    expect(first.getByText("20 KB")).toBeTruthy();
    const code = first.getByText("222222222222");
    expect(code.getAttribute("title")).toBe("2".repeat(64));
    const link = first.getByRole("link", { name: /Download/ });
    expect(link.getAttribute("href")).toBe("/api/v1/engagements/E%201/workpaper-copies/copy-2/download");
    expect(link.hasAttribute("download")).toBe(true);
    expect(screen.getByText("Fingerprint").getAttribute("title")).toMatch(/identifies this exact file/);
    expect(pages.calls[0]).toBe("/engagements/E%201/workpaper-copies?limit=10&offset=0");
  });

  it("shows ten and offers the older ones", async () => {
    pages.list = Array.from({ length: 12 }, (_, n) => copy(n));
    render(<SavedCopies engagementId="E1" refreshKey={0} />);
    fireEvent.click(await screen.findByRole("button", { name: "Show older copies (2 more)" }));
    await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(13));
    expect(screen.queryByRole("button", { name: /Show older/ })).toBeNull();
  });

  it("says plainly when the list cannot be loaded", async () => {
    pages.fail = true;
    render(<SavedCopies engagementId="E1" refreshKey={0} />);
    expect(await screen.findByText(/Could not load the saved copies\. Server error/)).toBeTruthy();
  });

  it("looks again after the download button is used", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<LiveOutputForTest />);
    await screen.findByText("Each workpaper you download is saved here.");
    pages.list = [copy(1)];
    const button = screen.getByRole("link", { name: /Download workpaper \(Excel\)/ });
    button.addEventListener("click", (e) => e.preventDefault()); // jsdom cannot download
    fireEvent.click(button);
    expect(within(screen.getByRole("region", { name: "Saved copies" })).queryByRole("table")).toBeNull(); // not yet: the file is still being sent
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2600);
    });
    expect(await screen.findByText("person1@firm.test")).toBeTruthy();
  });

  it("shows nothing on the demo site, which keeps no copies", () => {
    render(<LiveOutputForTest demo />);
    expect(screen.queryByRole("region", { name: "Saved copies" })).toBeNull();
    expect(pages.calls).toHaveLength(0);
  });
});

/* @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const lists = vi.hoisted(() => ({ items: [] as unknown[], calls: 0 }));
vi.mock("../../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../lib/api")>()),
  api: vi.fn(() => {
    lists.calls += 1;
    return Promise.resolve({ items: lists.items, total: lists.items.length, limit: 10, offset: 0 });
  }),
}));

import { safeFileName } from "../api/downloadFile";
import { LiveOutputForTest } from "./savedCopiesHarness";

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const file = (headers: Record<string, string> = {}) =>
  new Response("PK-bytes", {
    status: 200,
    headers: { "content-type": XLSX, "content-disposition": 'attachment; filename="Acme workpaper 2026-11-25.xlsx"', ...headers },
  });
const refusal = (status: number, detail: string) =>
  new Response(JSON.stringify({ detail }), { status, headers: { "content-type": "application/json" } });

const fetchMock = vi.fn();
const created: Blob[] = [];
const revoked: string[] = [];
const saved: { name: string; href: string }[] = [];

beforeEach(() => {
  lists.items = [];
  lists.calls = 0;
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  created.length = 0;
  revoked.length = 0;
  saved.length = 0;
  URL.createObjectURL = vi.fn((blob: Blob) => {
    created.push(blob);
    return `blob:test/${created.length}`;
  });
  URL.revokeObjectURL = vi.fn((url: string) => void revoked.push(url));
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    saved.push({ name: this.download, href: this.href });
  });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const button = () => document.querySelector(".s1-out-actions button") as HTMLButtonElement;

describe("downloading the workpaper from Output", () => {
  it("fetches with the session, saves under the server's file name, revokes the URL and refreshes the list at once", async () => {
    fetchMock.mockResolvedValue(file());
    render(<LiveOutputForTest />);
    await screen.findByText("Each workpaper you download is saved here.");
    const before = lists.calls;
    lists.items = [
      { id: "c1", created_at: "2026-11-25T10:00:00Z", prepared_by: "a@firm.test", file_name: "x", size_bytes: 2048, sha256: "a".repeat(64), app_version: "v", downloads: 1 },
    ];
    fireEvent.click(button());
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/engagements/E1/export", { credentials: "same-origin", cache: "no-store" });
    await waitFor(() => expect(saved).toHaveLength(1));
    expect(saved[0].name).toBe("Acme workpaper 2026-11-25.xlsx");
    await waitFor(() => expect(revoked).toEqual(["blob:test/1"]));
    expect(await screen.findByText("a@firm.test")).toBeTruthy(); // refreshed without a timer
    expect(lists.calls).toBeGreaterThan(before);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows 'Preparing…' and ignores a second click while busy", async () => {
    let finish: (r: Response) => void = () => undefined;
    fetchMock.mockReturnValue(new Promise<Response>((resolve) => (finish = resolve)));
    render(<LiveOutputForTest />);
    await screen.findByText("Each workpaper you download is saved here.");
    const first = button();
    fireEvent.click(first);
    fireEvent.click(first);
    await waitFor(() => expect(button().textContent).toMatch(/Preparing…/));
    expect(button().disabled).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    finish(file());
    await waitFor(() => expect(button().disabled).toBe(false));
    expect(saved).toHaveLength(1);
  });

  it.each([
    [503, "The workpaper could not be saved, so it was not downloaded. Please try again in a moment."],
    [409, "The GWP set chosen cannot be calculated."],
    [413, "This workpaper is larger than the 50 MB Sustentra keeps for each saved copy, so it was not downloaded. Please contact support."],
    [500, "This saved workpaper no longer matches its checksum, so it was not sent. Please contact support."],
  ])("a %i refusal shows its own words and saves no file", async (status, detail) => {
    fetchMock.mockResolvedValue(refusal(status, detail));
    render(<LiveOutputForTest />);
    await screen.findByText("Each workpaper you download is saved here.");
    fireEvent.click(button());
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(detail);
    expect(saved).toHaveLength(0);
    expect(created).toHaveLength(0);
    expect(fetchMock).toHaveBeenCalledTimes(1); // no automatic retry: a retry is a new record
    expect(button().disabled).toBe(false); // the person can try again
  });

  it("says so when the answer is not an Excel file, or the server cannot be reached", async () => {
    fetchMock.mockResolvedValueOnce(file({ "content-type": "text/html" }));
    render(<LiveOutputForTest />);
    await screen.findByText("Each workpaper you download is saved here.");
    fireEvent.click(button());
    expect((await screen.findByRole("alert")).textContent).toMatch(/did not send an Excel file, so nothing was saved/);
    expect(saved).toHaveLength(0);
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    fireEvent.click(button());
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/Could not reach the server/));
    expect(saved).toHaveLength(0);
  });

  it("hands an ended session (401) to the screen's own handler instead of showing a message", async () => {
    fetchMock.mockResolvedValue(refusal(401, "Not authenticated"));
    const onError = vi.fn(() => true);
    render(<LiveOutputForTest onError={onError} />);
    await screen.findByText("Each workpaper you download is saved here.");
    fireEvent.click(button());
    await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(saved).toHaveLength(0);
  });

  it("downloads a saved copy the same way, with one download at a time", async () => {
    lists.items = [
      { id: "c1", created_at: "2026-11-25T10:00:00Z", prepared_by: "a@firm.test", file_name: "x", size_bytes: 2048, sha256: "b".repeat(64), app_version: "v", downloads: 1 },
    ];
    let finish: (r: Response) => void = () => undefined;
    fetchMock.mockReturnValue(new Promise<Response>((resolve) => (finish = resolve)));
    render(<LiveOutputForTest />);
    const region = await screen.findByRole("region", { name: "Saved copies" });
    fireEvent.click(await within(region).findByRole("button", { name: /Download/ }));
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/engagements/E1/workpaper-copies/c1/download", expect.anything());
    expect(await within(region).findByRole("button", { name: /Preparing…/ })).toBeTruthy();
    expect(button().disabled).toBe(true); // the main button waits too
    finish(file());
    await waitFor(() => expect(saved).toHaveLength(1));
  });

  it("keeps the demo's fixed file as the plain link it is", () => {
    render(<LiveOutputForTest demo />);
    const link = screen.getByRole("link", { name: /Download workpaper \(Excel\)/ });
    expect(link.getAttribute("href")).toBe("/api/v1/engagements/E1/export");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("safeFileName", () => {
  it("drops paths and odd characters, and falls back", () => {
    expect(safeFileName("../../etc/passwd", "workpaper.xlsx")).toBe("etcpasswd.xlsx");
    expect(safeFileName('"><script>.xlsx', "workpaper.xlsx")).toBe("script.xlsx");
    expect(safeFileName("..", "workpaper.xlsx")).toBe("workpaper.xlsx");
    expect(safeFileName(null, "workpaper.xlsx")).toBe("workpaper.xlsx");
    expect(safeFileName("Acme workpaper 2026-11-25.xlsx", "x.xlsx")).toBe("Acme workpaper 2026-11-25.xlsx");
  });
});

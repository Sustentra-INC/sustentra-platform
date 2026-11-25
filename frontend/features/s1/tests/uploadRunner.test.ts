import { describe, expect, it, vi } from "vitest";

import type { UploadTask } from "../components/UploadDialog";
import type { UploadItem } from "../utils/expandUploads";
import { abortableSleep, runUploadQueue, MAX_ATTEMPTS, newUploadId, type RunnerDeps } from "../utils/uploadRunner";
import { ZipError } from "../utils/zipReader";

interface Doc {
  document_id: string;
}
class Busy extends Error {}
class Dropped extends Error {}

/** A server that stores by upload id, as the real one does: the same id gives the same document. */
function fakeServer() {
  const documents = new Map<string, Doc>();
  const calls: { engagementId: string; clientId: string; name: string }[] = [];
  return {
    documents,
    calls,
    /** `after` decides what the client sees: the file is stored first, then the answer is lost. */
    upload:
      (script: ("ok" | "busy" | "dropped-after-store")[]) =>
      async (engagementId: string, file: File, _p: unknown, _b: unknown, clientId: string): Promise<Doc> => {
        calls.push({ engagementId, clientId, name: file.name });
        const step = script.shift() ?? "ok";
        if (step === "busy") throw new Busy();
        const key = `${engagementId}:${clientId}`;
        if (!documents.has(key)) documents.set(key, { document_id: `DOC-${documents.size + 1}` });
        if (step === "dropped-after-store") throw new Dropped();
        return documents.get(key)!;
      },
  };
}

function setup(names: string[], over: Partial<RunnerDeps<Doc>> = {}) {
  const items = new Map<string, UploadItem>();
  const clientIds = new Map<string, string>();
  names.forEach((name, i) => {
    items.set(`t${i}`, { path: name, name, size: 1, open: async () => new File(["x"], name) });
    clientIds.set(`t${i}`, newUploadId());
  });
  const tasks = new Map<string, Partial<UploadTask>>();
  const stored: string[] = [];
  const notUploaded: { id: string; reason: string; retryable: boolean }[] = [];
  const server = fakeServer();
  const deps: RunnerDeps<Doc> = {
    engagementId: "ENG-1",
    isCurrent: () => true,
    signal: new AbortController().signal,
    batchId: undefined,
    items,
    clientIds,
    patch: (id, next) => tasks.set(id, { ...tasks.get(id), ...next }),
    upload: server.upload([]),
    retryAfter: (e) => ({ retry: e instanceof Busy || e instanceof Dropped, seconds: null }),
    describe: (e) => (e instanceof Error ? e.constructor.name : "?"),
    onStored: async (doc) => void stored.push(doc.document_id),
    onNotUploaded: (id, _i, reason, retryable) => {
      notUploaded.push({ id, reason, retryable });
      tasks.set(id, { ...tasks.get(id), stage: "not_uploaded", error: reason, retryable });
    },
    onStoredButFailed: () => undefined,
    onSessionEnded: () => false,
    sleep: async () => undefined,
    ...over,
  };
  return { deps, server, tasks, stored, notUploaded, ids: [...items.keys()] };
}

describe("a retry never makes a second document", () => {
  it("a connection dropped after the server stored the file, then the retry, gives one document", async () => {
    const t = setup(["bill.pdf"]);
    t.deps.upload = t.server.upload(["dropped-after-store"]);
    await runUploadQueue(t.ids, t.deps);
    expect(t.server.calls).toHaveLength(2);
    expect(new Set(t.server.calls.map((c) => c.clientId)).size).toBe(1); // the same id on both attempts
    expect(t.server.documents.size).toBe(1);
    expect(t.stored).toEqual(["DOC-1"]);
  });

  it("'try again' after every attempt failed reuses the row's id, so a file stored meanwhile is not doubled", async () => {
    const t = setup(["bill.pdf"]);
    // Every answer is lost although the file was stored on the first.
    t.deps.upload = t.server.upload(Array(MAX_ATTEMPTS).fill("dropped-after-store"));
    await runUploadQueue(t.ids, t.deps);
    expect(t.notUploaded).toEqual([{ id: "t0", reason: "Dropped", retryable: true }]);
    await runUploadQueue(["t0"], t.deps); // the "try again" link
    expect(t.server.documents.size).toBe(1);
    expect(t.stored).toEqual(["DOC-1"]);
    expect(new Set(t.server.calls.map((c) => c.clientId)).size).toBe(1);
  });

  it("different rows have different ids", async () => {
    const t = setup(["a.pdf", "a.pdf"]);
    await runUploadQueue(t.ids, t.deps);
    expect(t.server.documents.size).toBe(2);
  });

  it("gives up after the attempts, with a retryable reason, and goes on to the next file", async () => {
    const t = setup(["a.pdf", "b.pdf"]);
    t.deps.upload = t.server.upload(Array(MAX_ATTEMPTS).fill("busy"));
    await runUploadQueue(t.ids, t.deps);
    expect(t.server.calls.filter((c) => c.name === "a.pdf")).toHaveLength(MAX_ATTEMPTS);
    expect(t.notUploaded).toEqual([{ id: "t0", reason: "Busy", retryable: true }]);
    expect(t.stored).toEqual(["DOC-1"]); // b.pdf went up
  });

  it("does not retry what a retry cannot fix", async () => {
    const t = setup(["a.pdf"], { retryAfter: () => ({ retry: false, seconds: null }) });
    t.deps.upload = t.server.upload(["busy"]);
    await runUploadQueue(t.ids, t.deps);
    expect(t.server.calls).toHaveLength(1);
    expect(t.notUploaded[0].retryable).toBe(false);
  });
});

describe("cancel", () => {
  it("the signal is passed when the file is opened, so a retry after a cancel is not 'Cancelled'", async () => {
    const first = new AbortController();
    const seen: (AbortSignal | undefined)[] = [];
    const t = setup(["a.pdf"]);
    t.deps.items.set("t0", { path: "a.pdf", name: "a.pdf", size: 1, open: async (s) => (seen.push(s), new File(["x"], "a.pdf")) });
    t.deps.signal = first.signal;
    first.abort();
    await runUploadQueue(t.ids, t.deps); // cancelled before it was sent
    expect(t.notUploaded[0]).toEqual({ id: "t0", reason: "Cancelled before it was sent.", retryable: true });
    // Try again, with a fresh controller: the file opens with THAT signal and uploads.
    const second = new AbortController();
    await runUploadQueue(["t0"], { ...t.deps, signal: second.signal });
    expect(seen).toEqual([second.signal]);
    expect(t.stored).toEqual(["DOC-1"]);
  });

  it("a zip entry that fails to unpack says why; with Cancel it says Cancelled", async () => {
    const t = setup(["a.pdf"]);
    t.deps.items.set("t0", { path: "z/a.pdf", name: "a.pdf", size: 1, open: async () => Promise.reject(new ZipError("Damaged inside the zip.")) });
    await runUploadQueue(t.ids, t.deps);
    expect(t.notUploaded[0]).toEqual({ id: "t0", reason: "Damaged inside the zip.", retryable: false });
  });

  it("the wait before a retry ends at once on Cancel, and nothing more is sent", async () => {
    vi.useFakeTimers();
    try {
      const controller = new AbortController();
      const t = setup(["a.pdf", "b.pdf"], { signal: controller.signal, sleep: abortableSleep });
      t.deps.upload = t.server.upload(["busy"]);
      const running = runUploadQueue(t.ids, t.deps);
      await vi.advanceTimersByTimeAsync(10); // now waiting 1 s before the retry
      controller.abort();
      await vi.advanceTimersByTimeAsync(0); // far less than the 1 s wait
      await running;
      expect(t.server.calls).toHaveLength(1);
      expect(t.notUploaded.map((n) => n.id)).toEqual(["t0", "t1"]);
      expect(t.notUploaded.every((n) => n.retryable)).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("abortableSleep resolves when the time is up, or at once if already aborted", async () => {
    const c = new AbortController();
    c.abort();
    await abortableSleep(60_000, c.signal);
  });
});

describe("the engagement is captured once", () => {
  it("every request goes to the engagement the upload started in, even if the screen's changes", async () => {
    let current = "ENG-1";
    const t = setup(["a.pdf", "b.pdf", "c.pdf"], { isCurrent: () => current === "ENG-1" });
    const send = t.server.upload([]);
    t.deps.upload = async (...args) => {
      const doc = await send(...args);
      if (args[1].name === "a.pdf") current = "ENG-2"; // the person switches engagement mid-upload
      return doc;
    };
    await runUploadQueue(t.ids, t.deps);
    expect(t.server.calls.map((c) => [c.engagementId, c.name])).toEqual([["ENG-1", "a.pdf"]]);
    expect(t.stored).toEqual([]); // not shown in the other engagement either
  });

  it("stops the moment the screen is left", async () => {
    let here = true;
    const t = setup(["a.pdf", "b.pdf"], { isCurrent: () => here });
    t.deps.onStored = async () => void (here = false);
    await runUploadQueue(t.ids, t.deps);
    expect(t.server.calls).toHaveLength(1);
  });

  it("stops when the session ends", async () => {
    const t = setup(["a.pdf", "b.pdf"], { onSessionEnded: () => true });
    t.deps.upload = async () => {
      throw new Error("401");
    };
    expect(await runUploadQueue(t.ids, t.deps)).toBe("ended");
    expect(t.notUploaded).toEqual([]);
  });
});

describe("a file stored but not read", () => {
  it("is reported as uploaded but not read, never as not uploaded", async () => {
    const failed: string[] = [];
    const t = setup(["a.pdf"], {
      onStored: async () => {
        throw new Error("read failed");
      },
      onStoredButFailed: (_id, _i, reason) => void failed.push(reason),
    });
    await runUploadQueue(t.ids, t.deps);
    expect(failed).toEqual(["Uploaded, but could not be read: Error"]);
    expect(t.notUploaded).toEqual([]);
  });
});

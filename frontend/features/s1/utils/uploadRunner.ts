/**
 * Sends the files of one upload, one at a time. Kept apart from the screen so the rules that matter
 * can be tested: a retry never makes a second document (every attempt of a row carries the row's own
 * upload id, which the server answers with the document it already stored), Cancel stops the
 * waiting and the unpacking at once, and nothing is ever sent into an engagement other than the one
 * the upload started in.
 */
import type { UploadTask } from "../components/UploadDialog";
import type { UploadItem } from "./expandUploads";
import { ZipError } from "./zipReader";

/** A random id, made once per file row; the same value on every attempt and on "try again". */
export function newUploadId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Waits, but stops waiting the moment the signal aborts. */
export function abortableSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const done = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    };
    const timer = setTimeout(done, ms);
    signal.addEventListener("abort", done, { once: true });
  });
}

export const MAX_ATTEMPTS = 4; // the first try and three more

export interface RunnerDeps<Doc> {
  /** Fixed when the upload starts: every request of this run goes to this engagement. */
  engagementId: string;
  /** False once the person is in another engagement or has left: the run stops, sending nothing more. */
  isCurrent: () => boolean;
  signal: AbortSignal;
  batchId: string | undefined;
  items: Map<string, UploadItem>;
  /** The row's upload id, by task id. */
  clientIds: Map<string, string>;
  patch: (taskId: string, next: Partial<UploadTask>) => void;
  upload: (
    engagementId: string,
    file: File,
    onProgress: (fraction: number) => void,
    batchId: string | undefined,
    clientUploadId: string
  ) => Promise<Doc>;
  /** Whether a failed attempt is worth another try (busy server, dropped connection); gives the wait in seconds from the server if it said. */
  retryAfter: (error: unknown) => { retry: boolean; seconds: number | null };
  /** The words for a failure. */
  describe: (error: unknown) => string;
  /** The file is stored: show it, ask for its read. Throws when that fails (the file is still stored). */
  onStored: (doc: Doc, file: File, item: UploadItem, taskId: string) => Promise<void>;
  onNotUploaded: (taskId: string, item: UploadItem, reason: string, retryable: boolean) => void;
  onStoredButFailed: (taskId: string, item: UploadItem, reason: string) => void;
  /** Called with any error; true when it was the session ending (the run stops). */
  onSessionEnded: (error: unknown) => boolean;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
  now?: () => number;
}

/** Runs the tasks in order. Resolves with "ended" if the session ended, else "finished". */
export async function runUploadQueue<Doc>(taskIds: string[], deps: RunnerDeps<Doc>): Promise<"finished" | "ended"> {
  const sleep = deps.sleep ?? abortableSleep;
  const now = deps.now ?? (() => performance.now());
  for (const taskId of taskIds) {
    const item = deps.items.get(taskId);
    if (!item?.open) continue;
    if (!deps.isCurrent()) return "finished"; // another engagement: no more files go anywhere
    if (deps.signal.aborted) {
      deps.onNotUploaded(taskId, item, "Cancelled before it was sent.", true);
      continue;
    }
    let stored = false;
    try {
      deps.patch(taskId, { stage: "uploading", progress: 0, error: undefined, retryable: false });
      let file: File;
      try {
        file = await item.open(deps.signal);
      } catch (error) {
        const cancelled = deps.signal.aborted;
        deps.onNotUploaded(
          taskId,
          item,
          cancelled ? "Cancelled before it was sent." : error instanceof ZipError ? error.message : "Couldn't be unpacked from the zip.",
          cancelled
        );
        continue;
      }
      let last = 0;
      const onProgress = (fraction: number) => {
        const t = now();
        if (fraction < 1 && t - last < 150) return; // a tick per 150 ms, not per event
        last = t;
        deps.patch(taskId, { progress: fraction });
      };
      const clientId = deps.clientIds.get(taskId)!;
      let doc: Doc | undefined;
      for (let attempt = 1; doc === undefined; attempt++) {
        try {
          doc = await deps.upload(deps.engagementId, file, onProgress, deps.batchId, clientId);
        } catch (error) {
          const verdict = deps.retryAfter(error);
          if (!verdict.retry || attempt >= MAX_ATTEMPTS || deps.signal.aborted) throw error;
          deps.patch(taskId, { progress: 0 });
          const seconds = verdict.seconds ? Math.min(verdict.seconds, 10) : 2 ** (attempt - 1);
          await sleep(seconds * 1000, deps.signal);
          if (deps.signal.aborted) throw error; // Cancel ends the wait at once; the file is reported as not sent
        }
      }
      stored = true;
      if (!deps.isCurrent()) return "finished"; // stored in its own engagement; nothing of it is shown in another
      await deps.onStored(doc, file, item, taskId);
    } catch (error) {
      if (deps.onSessionEnded(error)) return "ended";
      if (stored) deps.onStoredButFailed(taskId, item, `Uploaded, but could not be read: ${deps.describe(error)}`);
      else {
        const verdict = deps.retryAfter(error);
        deps.onNotUploaded(taskId, item, deps.describe(error), verdict.retry);
      }
    }
  }
  return "finished";
}

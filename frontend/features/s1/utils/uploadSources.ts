/**
 * What the user picked or dropped, before anything is unpacked: files, folders (with each file's
 * path inside them) and zips. Folders are walked here; zips are opened in expandUploads.
 */
import { MAX_UPLOAD_FILES } from "../constants/uploads";

export interface UploadSource {
  file: File;
  /** The path the user sees: "bill.pdf", or "Plant A/2025/jan.pdf" for a file in a folder. */
  path: string;
}

/** A folder that could not be listed (too many files). It is shown as one row, with the reason. */
export interface RefusedSource {
  name: string;
  reason: string;
}

export interface UploadPick {
  sources: UploadSource[];
  refused: RefusedSource[];
}

/** Stop walking one dropped folder after this many files: far past the limit, never a hang. */
const WALK_STOP = MAX_UPLOAD_FILES * 5;

export function tooManyFilesReason(limit: number = MAX_UPLOAD_FILES): string {
  return `Has more than ${limit.toLocaleString("en-US")} files. Upload it in smaller parts.`;
}

/** Files from a file input; a folder input fills webkitRelativePath. */
export function pickFromFileList(list: FileList | File[]): UploadPick {
  const sources = Array.from(list).map((file) => ({
    file,
    path: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
  }));
  return { sources, refused: [] };
}

interface FsEntry {
  isFile: boolean;
  isDirectory: boolean;
  name: string;
  file?: (ok: (f: File) => void, fail: (e: unknown) => void) => void;
  createReader?: () => { readEntries: (ok: (e: FsEntry[]) => void, fail: (e: unknown) => void) => void };
}

/** readEntries returns at most 100 at a time: ask until it returns none. */
async function readAll(dir: FsEntry): Promise<FsEntry[]> {
  const reader = dir.createReader!();
  const all: FsEntry[] = [];
  for (;;) {
    const batch = await new Promise<FsEntry[]>((ok, fail) => reader.readEntries(ok, fail));
    if (batch.length === 0) return all;
    all.push(...batch);
  }
}

async function walk(entry: FsEntry, prefix: string, out: UploadSource[], budget: { left: number }): Promise<void> {
  if (budget.left <= 0) return;
  if (entry.isFile) {
    try {
      const file = await new Promise<File>((ok, fail) => entry.file!(ok, fail));
      budget.left -= 1;
      out.push({ file, path: `${prefix}${entry.name}` });
    } catch {
      // A file the browser can't open (removed while dragging): skipped, like an unreadable one.
    }
    return;
  }
  if (entry.isDirectory) {
    let children: FsEntry[] = [];
    try {
      children = await readAll(entry);
    } catch {
      return;
    }
    for (const child of children) await walk(child, `${prefix}${entry.name}/`, out, budget);
  }
}

/**
 * Files and folders from a drop. The entries must be taken from the event synchronously (the
 * browser clears them once the handler returns), so everything before the first await does that.
 */
export async function pickFromDrop(transfer: DataTransfer): Promise<UploadPick> {
  const plain = Array.from(transfer.files);
  const entries: (FsEntry | null)[] = Array.from(transfer.items ?? []).map((item) =>
    item.kind === "file" && typeof item.webkitGetAsEntry === "function"
      ? (item.webkitGetAsEntry() as unknown as FsEntry | null)
      : null
  );
  if (entries.length === 0 || entries.every((e) => !e)) return pickFromFileList(plain);

  const sources: UploadSource[] = [];
  const refused: RefusedSource[] = [];
  for (const [index, entry] of entries.entries()) {
    if (!entry) {
      if (plain[index]) sources.push({ file: plain[index], path: plain[index].name });
      continue;
    }
    if (entry.isFile) {
      await walk(entry, "", sources, { left: Infinity });
      continue;
    }
    const budget = { left: WALK_STOP };
    const found: UploadSource[] = [];
    await walk(entry, "", found, budget);
    if (budget.left <= 0) refused.push({ name: entry.name, reason: tooManyFilesReason() });
    else sources.push(...found);
  }
  return { sources, refused };
}

// ---------------------------------------------------------------------------------------------
// Names

/** Control characters, bidirectional marks and zero-width characters: shown as "_", never raw. */
const UNSAFE_CHARS = new RegExp(
  "[\\u0000-\\u001F\\u007F-\\u009F\\u200B-\\u200F\\u2028\\u2029\\u202A-\\u202E\\u2060-\\u206F\\uFEFF\\uFFFE\\uFFFF]",
  "g"
);

export function cleanText(text: string): string {
  return text.replace(UNSAFE_CHARS, "_");
}

/** Shortens the middle of a long text, keeping its ending (the file name and type). */
export function shortenMiddle(text: string, max: number): string {
  if (text.length <= max) return text;
  const tail = Math.floor((max - 1) * 0.6);
  return `${text.slice(0, max - 1 - tail)}…${text.slice(text.length - tail)}`;
}

/**
 * A path inside a zip or folder, made safe to show: slashes only, no empty or "." parts. Returns
 * null when it is unsafe (absolute, a drive letter, or going up with "..").
 */
export function safePath(raw: string): string | null {
  const slashed = raw.replace(/\\/g, "/");
  if (slashed.startsWith("/") || /^[A-Za-z]:/.test(slashed)) return null;
  const parts = slashed.split("/").filter((part) => part !== "" && part !== ".");
  if (parts.some((part) => part === "..")) return null;
  if (parts.length === 0) return null;
  return parts.map(cleanText).join("/");
}

/** System and hidden files that are never evidence: skipped, and counted in the summary. */
export function isJunkPath(path: string): boolean {
  const parts = path.split("/");
  const base = parts[parts.length - 1].toLowerCase();
  if (parts.some((part) => part === "__MACOSX" || part.startsWith("."))) return true;
  return base === "thumbs.db" || base === "desktop.ini" || base.startsWith("~$");
}

/** The name sent to the server: the last part of the path, at most 200 characters, keeping its type. */
export function baseNameOf(path: string): string {
  const base = path.split("/").pop() || path;
  if (base.length <= 200) return base;
  const dot = base.lastIndexOf(".");
  const ext = dot > 0 && base.length - dot <= 12 ? base.slice(dot) : "";
  return base.slice(0, 200 - ext.length) + ext;
}

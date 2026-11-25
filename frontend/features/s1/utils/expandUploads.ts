/**
 * Turns what was picked (files, folders, zips) into the list of single files to upload, one row
 * each, with a plain reason for every one that can't go. A zip is read in the browser; each file
 * inside is unpacked only when its turn to upload comes (item.open()), so a big zip is never in
 * memory at once. Nothing is dropped without being listed or counted.
 */
import {
  isReadableUpload,
  MAX_COMPRESSION_RATIO,
  MAX_UNPACKED_BYTES,
  MAX_UNPACKED_GB,
  MAX_UPLOAD_BYTES,
  MAX_UPLOAD_FILES,
  MAX_ZIP_BYTES,
  MAX_ZIP_ENTRIES,
  MAX_ZIP_MB,
  UPLOAD_TOO_LARGE,
  unreadableUploadMessage,
} from "../constants/uploads";
import { extractZipEntry, readZipEntries, ZipError } from "./zipReader";
import {
  baseNameOf,
  cleanText,
  isJunkPath,
  safePath,
  shortenMiddle,
  tooManyFilesReason,
  type UploadPick,
  type UploadSource,
} from "./uploadSources";

export interface UploadItem {
  /** Where the file came from, to show: "Plant A/2025/jan.pdf". */
  path: string;
  /** The name sent to the server: the last part of the path. */
  name: string;
  size: number;
  /** Present when the file can be uploaded; gives the bytes (a zip entry is unpacked now). The signal is
   *  the current upload's, passed at the moment of unpacking (a retry after a cancel gets a fresh one). */
  open?: (signal?: AbortSignal) => Promise<File>;
  /** Present when it can't be uploaded: why, in one plain line. */
  reason?: string;
}

export interface Expanded {
  items: UploadItem[];
  /** One line per folder or zip, e.g. "48 files found in Evidence.zip, 3 can't be read". */
  summaries: string[];
}

export interface Limits {
  maxFiles: number;
  maxZipBytes: number;
  maxUnpackedBytes: number;
  maxFileBytes: number;
  maxRatio: number;
  maxEntries: number;
}

export const DEFAULT_LIMITS: Limits = {
  maxFiles: MAX_UPLOAD_FILES,
  maxZipBytes: MAX_ZIP_BYTES,
  maxUnpackedBytes: MAX_UNPACKED_BYTES,
  maxFileBytes: MAX_UPLOAD_BYTES,
  maxRatio: MAX_COMPRESSION_RATIO,
  maxEntries: MAX_ZIP_ENTRIES,
};

export interface ExpandOptions {
  signal?: AbortSignal;
  onProgress?: (message: string) => void;
  limits?: Partial<Limits>;
}

const isZip = (file: { name: string; type?: string }) =>
  /\.zip$/i.test(file.name) || /^application\/(x-)?zip(-compressed)?$/i.test(file.type ?? "");

const plural = (n: number, word: string) => `${n.toLocaleString("en-US")} ${word}${n === 1 ? "" : "s"}`;
const MB = 1024 * 1024;

function display(path: string): string {
  return shortenMiddle(path, 300);
}

function fileItem(file: File, path: string, limits: Limits): UploadItem {
  const name = baseNameOf(path);
  const base = { path: display(path), name, size: file.size };
  if (file.size === 0) return { ...base, reason: "The file is empty." };
  if (file.size > limits.maxFileBytes) return { ...base, reason: UPLOAD_TOO_LARGE };
  if (!isReadableUpload({ name, type: file.type })) return { ...base, reason: unreadableUploadMessage(name) };
  const item: UploadItem = {
    ...base,
    // The name may be lengthened later to tell it from a file of the same name; the bytes are the same.
    open: async () => (item.name === file.name ? file : new File([file], item.name, { type: file.type })),
  };
  return item;
}

interface ZipResult {
  items: UploadItem[];
  /** Files found (not counting system files) and the ones that can't be uploaded. */
  found: number;
  unreadable: number;
  junk: number;
  /** The zip itself was refused: no summary line, one row with the reason. */
  refused: boolean;
}

async function expandZip(
  file: File,
  zipPath: string,
  prefix: string,
  budget: { unpacked: number },
  options: ExpandOptions,
  limits: Limits
): Promise<ZipResult> {
  const refuse = (reason: string): ZipResult => ({
    items: [{ path: display(zipPath), name: baseNameOf(zipPath), size: file.size, reason }],
    found: 0,
    unreadable: 0,
    junk: 0,
    refused: true,
  });
  if (file.size > limits.maxZipBytes) return refuse(`This zip is larger than ${MAX_ZIP_MB} MB. Upload it in smaller parts.`);
  let entries;
  try {
    entries = await readZipEntries(file, limits.maxEntries);
  } catch (error) {
    return refuse(error instanceof ZipError ? error.message : "This zip can't be opened.");
  }

  const files = entries.filter((e) => !e.isDirectory);
  let junk = 0;
  const candidates = files.filter((e) => {
    const safe = safePath(e.name);
    if (safe !== null && isJunkPath(safe)) {
      junk += 1;
      return false;
    }
    return true;
  });
  if (candidates.length > limits.maxFiles)
    return refuse(`This zip has more than ${limits.maxFiles.toLocaleString("en-US")} files. Upload it in smaller parts.`);
  const declared = candidates.reduce((sum, e) => sum + e.size, 0);
  if (declared > limits.maxUnpackedBytes) return refuse(`This zip unpacks to more than ${MAX_UNPACKED_GB} GB.`);

  const items: UploadItem[] = [];
  const seen = new Set<string>();
  for (const entry of candidates) {
    const safe = safePath(entry.name);
    if (safe === null) {
      items.push({
        path: display(prefix + cleanText(entry.name)),
        name: baseNameOf(cleanText(entry.name).replace(/\\/g, "/")),
        size: entry.size,
        reason: "Its path points outside the zip, so it was not opened.",
      });
      continue;
    }
    const path = prefix + safe;
    const name = baseNameOf(safe);
    const base = { path: display(path), name, size: entry.size };
    if (seen.has(safe)) {
      items.push({ ...base, reason: "Another file in this zip has the same path, so this one was not uploaded." });
      continue;
    }
    seen.add(safe);
    if (entry.isLink) items.push({ ...base, reason: "Shortcuts inside a zip aren't followed." });
    else if (entry.encrypted) items.push({ ...base, reason: "Password-protected, so it can't be opened." });
    else if (isZip({ name })) items.push({ ...base, reason: "A zip inside a zip isn't opened. Unpack it and upload it on its own." });
    else if (entry.size === 0) items.push({ ...base, reason: "The file is empty." });
    else if (entry.size > limits.maxFileBytes) items.push({ ...base, reason: UPLOAD_TOO_LARGE });
    else if (entry.method !== 0 && entry.method !== 8)
      items.push({ ...base, reason: "Packed in a way that can't be opened here." });
    else if (entry.size > MB && entry.size / Math.max(1, entry.compressedSize) > limits.maxRatio)
      items.push({ ...base, reason: "Unpacks to far more than it should, so it was not opened." });
    else if (!isReadableUpload({ name })) items.push({ ...base, reason: unreadableUploadMessage(name) });
    else {
      let counted = 0;
      const item: UploadItem = {
        ...base,
        open: async (signal?: AbortSignal) => {
          budget.unpacked -= counted; // a retry unpacks it again: count it once
          counted = 0;
          const bytes = await extractZipEntry(file, entry, {
            maxBytes: limits.maxFileBytes,
            maxRatio: limits.maxRatio,
            signal,
            onBytes: (n) => {
              budget.unpacked += n;
              counted += n;
              if (budget.unpacked > limits.maxUnpackedBytes)
                throw new ZipError(`Stopped: the zips unpack to more than ${MAX_UNPACKED_GB} GB in all.`);
            },
          });
          return new File([bytes.buffer as ArrayBuffer], item.name);
        },
      };
      items.push(item);
    }
  }
  return {
    items,
    found: items.length,
    unreadable: items.filter((i) => i.reason).length,
    junk,
    refused: false,
  };
}

function summaryLine(name: string, found: number, unreadable: number, junk: number): string {
  let line = `${plural(found, "file")} found in ${name}`;
  if (unreadable) line += `, ${unreadable.toLocaleString("en-US")} can't be read`;
  if (junk) line += `, ${plural(junk, "system file")} skipped`;
  return line;
}

type Unit =
  | { kind: "file"; source: UploadSource }
  | { kind: "folder"; root: string; sources: UploadSource[] };

export async function expandUploads(pick: UploadPick, options: ExpandOptions = {}): Promise<Expanded> {
  const limits = { ...DEFAULT_LIMITS, ...options.limits };
  const items: UploadItem[] = [];
  const summaries: string[] = [];
  const budget = { unpacked: 0 };
  let total = 0;

  for (const refused of pick.refused)
    items.push({ path: display(cleanText(refused.name)), name: cleanText(refused.name), size: 0, reason: refused.reason });

  // Group by what was picked: loose files, and each folder as one unit.
  const units: Unit[] = [];
  const folders = new Map<string, UploadSource[]>();
  for (const source of pick.sources) {
    const slash = source.path.indexOf("/");
    if (slash < 0) {
      units.push({ kind: "file", source });
      continue;
    }
    const root = source.path.slice(0, slash);
    let group = folders.get(root);
    if (!group) {
      group = [];
      folders.set(root, group);
      units.push({ kind: "folder", root, sources: group });
    }
    group.push(source);
  }
  const alone = pick.sources.length === 1;

  const room = (n: number, label: string, path: string): UploadItem | null =>
    total + n > limits.maxFiles
      ? {
          path: display(path),
          name: baseNameOf(path),
          size: 0,
          reason: `${label} would take this upload past ${limits.maxFiles.toLocaleString("en-US")} files. Upload it separately.`,
        }
      : null;

  for (const unit of units) {
    if (options.signal?.aborted) break;
    await Promise.resolve(); // let the page breathe between units
    if (unit.kind === "file") {
      const { source } = unit;
      const path = cleanText(source.path);
      if (isZip(source.file)) {
        options.onProgress?.(`Looking through ${path}…`);
        const result = await expandZip(source.file, path, alone ? "" : `${path}/`, budget, options, limits);
        const over = result.refused ? null : room(result.items.length, path, path);
        if (over) {
          items.push(over);
          continue;
        }
        total += result.refused ? 0 : result.items.length;
        items.push(...result.items);
        if (!result.refused) summaries.push(summaryLine(path, result.found, result.unreadable, result.junk));
      } else {
        const over = room(1, path, path);
        if (over) items.push(over);
        else {
          total += 1;
          items.push(fileItem(source.file, path, limits));
        }
      }
      continue;
    }

    // A folder.
    options.onProgress?.(`Looking through ${unit.root}…`);
    let junk = 0;
    const folderItems: UploadItem[] = [];
    let found = 0;
    for (const source of unit.sources) {
      if (options.signal?.aborted) break;
      const safe = safePath(source.path);
      if (safe === null) continue;
      if (isJunkPath(safe)) {
        junk += 1;
        continue;
      }
      if (isZip(source.file)) {
        const result = await expandZip(source.file, safe, `${safe}/`, budget, options, limits);
        found += result.items.length;
        folderItems.push(...result.items);
        junk += result.junk;
      } else {
        found += 1;
        folderItems.push(fileItem(source.file, safe, limits));
      }
      if (found > limits.maxFiles) break;
    }
    if (found > limits.maxFiles) {
      items.push({ path: display(cleanText(unit.root)), name: cleanText(unit.root), size: 0, reason: tooManyFilesReason(limits.maxFiles) });
      continue;
    }
    const over = room(found, unit.root, cleanText(unit.root));
    if (over) {
      items.push(over);
      continue;
    }
    total += found;
    items.push(...folderItems);
    summaries.push(summaryLine(cleanText(unit.root), found, folderItems.filter((i) => i.reason).length, junk));
  }
  tellSameNamesApart(items);
  return { items, summaries };
}

/** What the server will keep of a name (backend/app/services/local_storage_service.py,
 *  _sanitize_file_name): anything outside A-Z a-z 0-9 . _ - becomes "_". Two names that match after
 *  this would look the same in Evidence, so this is the form compared. Case-insensitive. */
function storedForm(name: string): string {
  return name.replace(/[^A-Za-z0-9._-]+/g, "_").trim().toLowerCase();
}

/** The name with its type kept and its length capped, as sent. */
function capName(name: string): string {
  return baseNameOf(name);
}

/**
 * Files in one pick whose names match (as the server will store them) are sent with the shortest
 * parent folders that tell them apart, joined with " - ": "Plant A - bill.pdf", "Plant B - bill.pdf".
 * A file with a name of its own keeps it exactly. The row still shows the full path.
 */
export function tellSameNamesApart(items: UploadItem[]): void {
  const sendable = items.filter((item) => item.open);
  const groups = new Map<string, UploadItem[]>();
  for (const item of sendable) {
    const key = storedForm(item.name);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  for (const group of groups.values()) {
    if (group.length < 2) continue;
    const parents = group.map((item) => item.path.split("/").slice(0, -1));
    const deepest = Math.max(...parents.map((p) => p.length));
    const nameAt = (index: number, depth: number) => {
      const own = depth === 0 ? [] : parents[index].slice(-depth);
      return capName([...own, group[index].name].join(" - "));
    };
    let depth = 1;
    while (depth < deepest && new Set(group.map((_, i) => storedForm(nameAt(i, depth)))).size < group.length) depth++;
    const renamed = group.map((_, i) => nameAt(i, depth));
    group.forEach((item, i) => {
      item.name = renamed[i];
    });
  }
  // Still the same (names with no letters the server keeps, the same folders under other zips, or a
  // file already called "A - bill.pdf"): number the later ones, so no two sent names are equal.
  const seen = new Map<string, number>();
  for (const item of sendable) {
    const key = storedForm(item.name);
    const n = (seen.get(key) ?? 0) + 1;
    seen.set(key, n);
    if (n > 1) {
      const dot = item.name.lastIndexOf(".");
      const stem = dot > 0 ? item.name.slice(0, dot) : item.name;
      const ext = dot > 0 ? item.name.slice(dot) : "";
      item.name = capName(`${stem} (${n})${ext}`);
      seen.set(storedForm(item.name), 1);
    }
  }
}

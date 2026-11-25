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
  /** Present when the file can be uploaded; gives the bytes (a zip entry is unpacked now). */
  open?: () => Promise<File>;
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
  return { ...base, open: async () => file };
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
      items.push({
        ...base,
        open: async () => {
          budget.unpacked -= counted; // a retry unpacks it again: count it once
          counted = 0;
          const bytes = await extractZipEntry(file, entry, {
            maxBytes: limits.maxFileBytes,
            maxRatio: limits.maxRatio,
            signal: options.signal,
            onBytes: (n) => {
              budget.unpacked += n;
              counted += n;
              if (budget.unpacked > limits.maxUnpackedBytes)
                throw new ZipError(`Stopped: the zips unpack to more than ${MAX_UNPACKED_GB} GB in all.`);
            },
          });
          return new File([bytes.buffer as ArrayBuffer], name);
        },
      });
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
  return { items, summaries };
}

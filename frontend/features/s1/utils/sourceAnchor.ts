import type { EvidenceFormat } from "../types/evidence";

/**
 * Where a value was read in a file that has no page to outline it on (a workbook, a CSV, a
 * Word or text file). The numbering is the backend parsers' own, so it matches the content
 * GET /documents/{id}/content returns:
 * - cell: an Excel sheet and cell ("2025 log", D2), as row and 0-based column;
 * - row: a CSV row number in the file, with its 0-based column when the extractor recorded
 *   it (cell_or_range "E2"); without one the column is found by the value's text;
 * - line: the n-th non-empty line of a Word or text file, and which part of it ("part 2":
 *   lines split on tabs, 2+ spaces or pipes, as the extractor splits them).
 */
export type SourceAnchor =
  | { kind: "cell"; sheet: string; row: number; column: number }
  | { kind: "row"; row: number; column?: number }
  | { kind: "line"; line: number; part?: number };

interface ReferenceLike {
  sheet_name?: string | null;
  cell_or_range?: string | null;
  parser_block_ids?: string[] | null;
}

/** "D" -> 3, "AA" -> 26. */
export function columnIndex(letters: string): number {
  let n = 0;
  for (const ch of letters.toUpperCase()) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n - 1;
}

/** 3 -> "D", 26 -> "AA". */
export function columnLetter(index: number): string {
  let n = index + 1;
  let out = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

const A1 = /^\$?([A-Za-z]{1,3})\$?(\d+)$/;

export function anchorOf(format: EvidenceFormat | undefined, reference: ReferenceLike | null | undefined): SourceAnchor | null {
  if (!reference) return null;
  const firstBlock = reference.parser_block_ids?.[0] ?? "";
  const cell = A1.exec((reference.cell_or_range ?? "").split(":")[0]);
  // A workbook cell, whatever the file is called (.xlsx, .xlsm).
  if (reference.sheet_name && cell) {
    return { kind: "cell", sheet: reference.sheet_name, row: Number(cell[2]), column: columnIndex(cell[1]) };
  }
  if (format === "csv") {
    if (cell) return { kind: "row", row: Number(cell[2]), column: columnIndex(cell[1]) };
    const row = /^csv_parser-r(\d+)-b\d+$/.exec(firstBlock) ?? /^row (\d+)$/.exec(reference.cell_or_range ?? "");
    return row ? { kind: "row", row: Number(row[1]) } : null;
  }
  if (format === "docx" || format === "other") {
    const line = /^(?:docx_parser|text_parser)-p1-b(\d+)$/.exec(firstBlock);
    if (!line) return null;
    const part = /^part (\d+)$/.exec(reference.cell_or_range ?? "");
    return part ? { kind: "line", line: Number(line[1]), part: Number(part[1]) } : { kind: "line", line: Number(line[1]) };
  }
  return null;
}

/** The parts a line splits into, as the extractor splits it: [start, end) of each, numbered
 *  from 1 counting empty pieces too (Python's re.split and String.split agree on these). */
export function lineParts(line: string): Map<number, [number, number]> {
  const parts = new Map<number, [number, number]>();
  const lead = line.length - line.trimStart().length;
  const text = line.trim();
  const separator = /\t+|\s{2,}|\s*\|\s*/g;
  let at = 0;
  let index = 1;
  for (const match of text.matchAll(separator)) {
    if (match[0].length === 0) continue;
    addPart(parts, text, at, match.index ?? at, lead, index);
    at = (match.index ?? at) + match[0].length;
    index += 1;
  }
  addPart(parts, text, at, text.length, lead, index);
  return parts;
}

function addPart(parts: Map<number, [number, number]>, text: string, from: number, to: number, lead: number,
  index: number) {
  const piece = text.slice(from, to);
  if (!piece.trim()) return;
  const start = from + (piece.length - piece.trimStart().length);
  const end = to - (piece.length - piece.trimEnd().length);
  parts.set(index, [start + lead, end + lead]);
}

function squash(text: string): string {
  return text.toLowerCase().replace(/\s+/g, " ").trim();
}

/** `text` lower-cased with runs of whitespace as one space, and where each kept character came from. */
function flatten(text: string): { flat: string; at: number[] } {
  const at: number[] = [];
  let flat = "";
  let space = true;
  for (let i = 0; i < text.length; i += 1) {
    if (/\s/.test(text[i])) {
      if (!space) {
        flat += " ";
        at.push(i);
      }
      space = true;
      continue;
    }
    flat += text[i].toLowerCase();
    at.push(i);
    space = false;
  }
  return { flat, at };
}

/**
 * Every place `needle` sits in `text` as a whole token, case and spacing aside: never inside
 * a longer number or word ("12" is not found in "01/12/2025" or "112"), and "1200" also finds
 * "1,200". Each as a [start, end) range of `text`.
 */
export function findTokens(text: string, needle: string | null | undefined): [number, number][] {
  const wanted = squash(needle ?? "");
  if (!wanted) return [];
  const { flat, at } = flatten(text);
  const out: [number, number][] = [];
  const add = (start: number, end: number) => {
    if (!out.some(([s]) => s === start)) out.push([start, end]);
  };
  const isWord = (ch: string | undefined) => ch !== undefined && /[0-9a-z]/.test(ch);
  const search = (hay: string, map: number[], what: string) => {
    let from = 0;
    while (what && from <= hay.length) {
      const i = hay.indexOf(what, from);
      if (i < 0) break;
      const before = hay[i - 1];
      const after = hay[i + what.length];
      // A number is not a token inside a longer one: "12" in 1.12, 1,120, 01/12/2025, 10:12, 2025-12-31.
      const joiner = (ch: string | undefined) => ch !== undefined && "/.,:-".includes(ch);
      const digit = (ch: string | undefined) => ch !== undefined && /\d/.test(ch);
      const insideNumber =
        (joiner(before) && digit(hay[i - 2]) && digit(what[0])) ||
        (joiner(after) && digit(hay[i + what.length + 1]) && digit(what[what.length - 1]));
      if (!isWord(before) && !isWord(after) && !insideNumber) add(map[i], map[i + what.length - 1] + 1);
      from = i + 1;
    }
  };
  search(flat, at, wanted);
  // Digits grouped with commas on either side ("28,100" for "28100", and the reverse).
  const keep: number[] = [];
  let bare = "";
  for (let i = 0; i < flat.length; i += 1) {
    if (flat[i] === "," && /\d/.test(flat[i - 1] ?? "") && /\d/.test(flat[i + 1] ?? "")) continue;
    bare += flat[i];
    keep.push(at[i]);
  }
  search(bare, keep, wanted.replace(/(?<=\d),(?=\d)/g, ""));
  return out.sort((a, b) => a[0] - b[0]);
}

/** The first whole-token place `needle` sits in `text`, or null. */
export function findInText(text: string, needle: string | null | undefined): [number, number] | null {
  return findTokens(text, needle)[0] ?? null;
}

/** Same text, ignoring case, spacing and digit grouping ("1,200" equals "1200"). */
export function sameText(a: string | null | undefined, b: string | null | undefined): boolean {
  const norm = (s: string | null | undefined) => squash(s ?? "").replace(/(?<=\d),(?=\d)/g, "");
  return norm(a) !== "" && norm(a) === norm(b);
}

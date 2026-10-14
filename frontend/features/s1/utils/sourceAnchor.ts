import type { EvidenceFormat } from "../types/evidence";

/**
 * Where a value was read in a file that has no page to outline it on (a workbook, a CSV, a
 * Word or text file). The numbering is the backend parsers' own, so it matches the content
 * GET /documents/{id}/content returns:
 * - cell: an Excel sheet and cell ("2025 log", D2), as row and 0-based column;
 * - row: a CSV row number in the file (the column is found by the value's text);
 * - line: the n-th non-empty line of a Word or text file.
 */
export type SourceAnchor =
  | { kind: "cell"; sheet: string; row: number; column: number }
  | { kind: "row"; row: number }
  | { kind: "line"; line: number };

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

export function anchorOf(format: EvidenceFormat | undefined, reference: ReferenceLike | null | undefined): SourceAnchor | null {
  if (!reference) return null;
  const firstBlock = reference.parser_block_ids?.[0] ?? "";
  if (format === "xlsx") {
    const cell = /^\$?([A-Za-z]{1,3})\$?(\d+)/.exec(reference.cell_or_range ?? "");
    return reference.sheet_name && cell
      ? { kind: "cell", sheet: reference.sheet_name, row: Number(cell[2]), column: columnIndex(cell[1]) }
      : null;
  }
  if (format === "csv") {
    const row = /^csv_parser-r(\d+)-b\d+$/.exec(firstBlock) ?? /^row (\d+)$/.exec(reference.cell_or_range ?? "");
    return row ? { kind: "row", row: Number(row[1]) } : null;
  }
  if (format === "docx" || format === "other") {
    const line = /^(?:docx_parser|text_parser)-p1-b(\d+)$/.exec(firstBlock);
    return line ? { kind: "line", line: Number(line[1]) } : null;
  }
  return null;
}

function squash(text: string): string {
  return text.toLowerCase().replace(/\s+/g, " ").trim();
}

/** Where `needle` sits in `text` (case and spacing aside, "1200" also finds "1,200"), as a
 *  [start, end) range of `text`, or null. */
export function findInText(text: string, needle: string | null | undefined): [number, number] | null {
  const wanted = squash(needle ?? "");
  if (wanted.replace(/ /g, "").length < 1) return null;
  // Map each kept character of the squashed text back to its index in `text`.
  const kept: number[] = [];
  let flat = "";
  let lastSpace = true;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (/\s/.test(ch)) {
      if (!lastSpace) {
        flat += " ";
        kept.push(i);
      }
      lastSpace = true;
      continue;
    }
    flat += ch.toLowerCase();
    kept.push(i);
    lastSpace = false;
  }
  for (const variant of new Set([wanted, wanted.replace(/,/g, "")])) {
    const at = flat.indexOf(variant);
    if (at >= 0) return [kept[at], kept[at + variant.length - 1] + 1];
  }
  const noCommas = flat.replace(/,/g, "");
  const at = noCommas.indexOf(wanted.replace(/,/g, ""));
  if (at < 0) return null;
  // Positions in the comma-free text: walk back to the original indices.
  const map: number[] = [];
  for (let i = 0; i < flat.length; i += 1) if (flat[i] !== ",") map.push(kept[i]);
  return [map[at], map[at + wanted.replace(/,/g, "").length - 1] + 1];
}
